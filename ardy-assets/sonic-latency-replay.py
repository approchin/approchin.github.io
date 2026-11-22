"""Paired SONIC checkpoints on identical G1 references, sampled at 50 Hz."""

import argparse
from dataclasses import dataclass
from pathlib import Path
import io
import json
import os
import sys
import time
import urllib.request
import zipfile

import mujoco
import numpy as np
import onnxruntime as ort
import yaml
from scipy.spatial.transform import Rotation, Slerp

ROOT = Path('/content/ardy-sonic-followup')
sys.path.insert(0, str(ROOT / 'humantracker/src'))
from humantracker.eval.backends.sonic import (
    CTRL_DT, DEFAULT_ANGLES_ISAB, ISAB_TO_MUJ, SONIC_DEFAULT_QPOS, SonicMjSim, SonicObsBuilder,
    action_to_motor_targets,
)
from humantracker.eval.core.geometry import get_sensor_data

XML = ROOT / 'humantracker/storage/assets/unitree_g1_5010/scene_mjx_track_papergray.xml'


@dataclass(frozen=True)
class PolicySpec:
    name: str
    directory: Path
    encoder_dim: int
    anchor_start: int
    stride: int

    @property
    def offsets(self):
        return np.arange(10, dtype=np.int64) * self.stride


SPECS = (
    PolicySpec('default', ROOT / 'sonic', 1762, 601, 5),
    PolicySpec('low_latency', ROOT / 'sonic/low_latency', 1247, 584, 1),
)

CONFIGS = {
    'G1_H52_patch_52lookahead_': 'h52_replan',
    'G1_H8_whole_52lookahead_': 'h8_52',
    'G1_H52_': 'h52_whole',
    'G1_H8_': 'h8_native',
}
TIMED_CONFIGS = {'h8_52', 'h52_whole'}


class Controller:
    def __init__(self, spec, threads):
        self.spec = spec
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.log_severity_level = 3
        self.encoder = self._session('model_encoder.onnx', options, spec.encoder_dim, 64)
        self.decoder = self._session('model_decoder.onnx', options, 994, 29)
        self.encoder_input_name = self.encoder.get_inputs()[0].name
        self.decoder_input_name = self.decoder.get_inputs()[0].name

    def _session(self, filename, options, expected_in, expected_out):
        session = ort.InferenceSession(
            str(self.spec.directory / filename), sess_options=options, providers=['CPUExecutionProvider'],
        )
        actual_in = session.get_inputs()[0]
        actual_out = session.get_outputs()[0]
        if actual_in.shape != [1, expected_in] or actual_out.shape != [1, expected_out]:
            raise ValueError(f'{self.spec.name} {filename}: {actual_in.shape}, {actual_out.shape}')
        if actual_in.type != 'tensor(float)' or actual_out.type != 'tensor(float)':
            raise ValueError(f'Unexpected ONNX input/output type in {filename}')
        return session

    def eval_step(self, obs, encoder_obs):
        token = self.encoder.run(None, {self.encoder_input_name: encoder_obs})[0]
        decoder_input = obs.build_decoder_obs(token)
        return self.decoder.run(None, {self.decoder_input_name: decoder_input})[0][0]


def verify_configs():
    for spec in SPECS:
        source = (spec.directory / 'observation_config.yaml').read_text()
        parsed = yaml.safe_load(source)
        if not isinstance(parsed, dict):
            raise ValueError(f'Invalid official YAML for {spec.name}')
        for term in ('motion_joint_positions', 'motion_joint_velocities', 'motion_anchor_orientation'):
            name = f'{term}_10frame_step{spec.stride}'
            if name not in source:
                raise ValueError(f'Official G1 configuration missing {name}')
        print('POLICY', spec.name, spec.encoder_dim, 'last reference ms', 20*int(spec.offsets[-1]), flush=True)


def encoder_input(builder, spec, requested, base_quat, last_visible, realtime):
    frames = np.minimum(requested, last_visible)
    positions = builder.ref_jpos_isab[frames]
    velocity = builder.ref_jvel_isab[frames]
    if realtime:
        velocity = velocity.copy()
        velocity[frames >= last_visible] = 0
    obs = np.zeros((1, spec.encoder_dim), dtype=np.float32)
    obs[0, 4:294] = positions.ravel()
    obs[0, 294:584] = velocity.ravel()
    obs[0, spec.anchor_start:spec.anchor_start + 60] = np.concatenate(
        [builder._anchor_ori(int(frame), base_quat) for frame in frames],
    )
    return obs


def resample(q25, model):
    q25 = np.ascontiguousarray(q25, dtype=np.float64)
    if q25.shape != (240, 36) or not np.isfinite(q25).all():
        raise ValueError(f'Expected 240 by 36 finite G1 qpos, got {q25.shape}')
    source_t = np.arange(len(q25)) / 25
    target_t = np.arange(2*len(q25) - 1) / 50
    q = np.stack([np.interp(target_t, source_t, c) for c in q25.T], axis=1)
    q[:, 3:7] = Slerp(source_t, Rotation.from_quat(q25[:, 3:7], scalar_first=True))(
        target_t,
    ).as_quat(scalar_first=True)
    q[:, :2] -= q[:1, :2].copy()
    vel = np.zeros((len(q), model.nv))
    for i in range(len(q)-1):
        mujoco.mj_differentiatePos(model, vel[i], CTRL_DT, q[i], q[i+1])
    vel[-1] = vel[-2]
    return q, vel


def commanded_path(info, q25):
    increments = np.zeros((len(q25), 2))
    events = sorted(info['events'], key=lambda event: event['frame'])
    for i, event in enumerate(events):
        start = int(event['frame'])
        end = int(events[i+1]['frame']) if i+1 < len(events) else len(q25)
        dt = np.arange(1, end-start+1) / 25
        action = event['intent']
        if action == 'walk':
            increments[start:end, 0] = .55/25
        elif action == 'left':
            yaw = np.minimum(dt/1.2, 1) * np.pi/2
            increments[start:end] = (.55/25)*np.column_stack((np.cos(yaw), np.sin(yaw)))
        elif action != 'stop':
            raise ValueError(f'Unknown path intent: {action}')
    target25 = np.cumsum(increments, axis=0)
    actual_error = np.linalg.norm(q25[:, :2]-target25,axis=1).mean()
    if not np.isclose(actual_error, info['mean_root_path_error_m'], atol=3e-4):
        raise ValueError(f"Command path disagrees with ARDY exporter: {actual_error} vs {info['mean_root_path_error_m']}")
    source = np.arange(len(q25)) / 25
    sample = np.arange(2*len(q25)-1) / 50
    return np.column_stack([np.interp(sample,source,c) for c in target25.T])-q25[:1,:2]


def inspect_reference(model, q, reference_stop_index):
    data = mujoco.MjData(model)
    site_ids = [
        s for s in range(model.nsite)
        if 'foot' in (mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_SITE, s) or '').lower()
    ]
    if len(site_ids) < 2:
        return {'foot_site_names': []}
    min_height = []
    end = min(101, max(1, reference_stop_index))
    for p in q[:end]:
        data.qpos[:] = p
        mujoco.mj_forward(model, data)
        min_height.append(float(data.site_xpos[site_ids, 2].min()))
    return dict(
        foot_site_names=[mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_SITE, s) for s in site_ids],
        first_2s_foot_median_z_m=float(np.median(min_height)),
        first_2s_foot_min_z_m=float(np.min(min_height)),
        first_2s_foot_above_5cm_fraction=float(np.mean(np.array(min_height)>.05)),
    )


def arrivals_for(ends, times, events):
    starts = np.r_[0, ends[:-1]]
    if len(ends) != len(times) or not len(ends) or np.any(np.diff(ends) <= 0):
        raise ValueError('Invalid generation ledger')
    allowed = {int(e['frame']): float(e['ready_s']) for e in events
               if e['frame'] != 0 and e['status'] == 'applied'}
    arrivals = [0.0]
    for start, actual_compute in zip(starts[1:], times[1:]):
        arrivals.append(max(arrivals[-1], allowed.get(int(start), 0.0)) + float(actual_compute))
    return np.asarray(arrivals)


def visible_limits(mode, n, ends, elapsed, events):
    time50 = np.arange(n) / 50
    if mode == 'full':
        return np.full(n, n-1), np.zeros(n, dtype=bool)
    if mode == 'on_time':
        ready = np.r_[0, ends[:-1]] / 25
    else:
        ready = arrivals_for(ends, elapsed, events)
    known = ends[np.searchsorted(ready, time50, side='right')-1]
    last_interp = np.minimum(n-1, 2*(known-1))
    current_unavailable = (np.arange(n)//2) >= known
    return last_interp, current_unavailable


def verify_default_contract(ref, vel):
    official = SonicObsBuilder({'qpos': ref, 'qvel': vel}, encoder_dim=1762)
    official.reset(ref[0, 3:7])
    for k in (0, 17, 93, len(ref)-3):
        q = ref[k, 3:7]
        ours = encoder_input(official, SPECS[0], k+SPECS[0].offsets, q, len(ref)-1, False)
        upstream = official.build_encoder_obs(k, q)
        np.testing.assert_array_equal(ours, upstream)


def replay(sim, policy, ref, vel, ends, elapsed, events, stop_frame, delivery):
    """Advance MuJoCo using only the selected policy and available reference."""
    sim.init_qpos = ref[0].astype(np.float32)
    state = sim.reset(sim.init_state())
    obs = SonicObsBuilder({'qpos': ref, 'qvel': vel}, encoder_dim=policy.spec.encoder_dim)
    obs.reset(state.mj_data.qpos[3:7].copy())
    action = np.zeros(29, dtype=np.float32)
    q_positions = np.empty_like(ref)
    policy_ms = np.empty(len(ref))
    loop_ms = np.empty(len(ref))
    limits, current_unavailable = visible_limits(delivery, len(ref), ends, elapsed, events)
    missing = 0
    needed = 0
    for tick in range(len(ref)):
        tic = time.perf_counter_ns()
        q = state.mj_data.qpos.copy()
        dq = state.mj_data.qvel
        q_positions[tick] = q  # compare two states at the same pre-step timestamp
        gyro = get_sensor_data(sim.mj_model, state.mj_data, 'gyro_pelvis')
        obs.update_history(gyro, q[7:][ISAB_TO_MUJ]-DEFAULT_ANGLES_ISAB, dq[6:][ISAB_TO_MUJ],
                           action, q[3:7])
        requested = tick + policy.spec.offsets
        within_clip = (requested < len(ref)) & (requested > tick)
        missing += int(np.count_nonzero(within_clip & (requested > limits[tick])))
        needed += int(np.count_nonzero(within_clip))
        features = encoder_input(obs, policy.spec, requested, q[3:7], limits[tick], delivery!='full')
        infer_start = time.perf_counter_ns()
        action = policy.eval_step(obs, features)
        policy_ms[tick] = (time.perf_counter_ns() - infer_start)/1e6
        state = sim.step(state, action_to_motor_targets(action))
        loop_ms[tick] = (time.perf_counter_ns() - tic)/1e6
    if not np.isfinite(q_positions).all() or not np.isfinite(action).all():
        raise RuntimeError(f'{policy.spec.name} diverged to a non-finite state')
    root_diff = np.linalg.norm(q_positions[:, :2] - ref[:, :2], axis=1)
    joints_diff = q_positions[:, 7:] - ref[:, 7:]
    joint_mae = np.degrees(np.abs(np.arctan2(np.sin(joints_diff), np.cos(joints_diff))).mean())
    fallen = np.convolve(q_positions[:, 2] < .35, np.ones(5, dtype=int), mode='valid') >= 5
    stop_tick = min(2*stop_frame, len(ref)-51)
    stop_tail = q_positions[stop_tick:stop_tick+51, :2]
    stop_move = np.linalg.norm(np.diff(stop_tail, axis=0), axis=1).sum()
    stop_net = np.linalg.norm(stop_tail[-1] - stop_tail[0])
    warm_timing = policy_ms[20:]
    return dict(
        root_xy_mae_m=float(root_diff.mean()), root_xy_final_m=float(root_diff[-1]),
        first_2s_actual_forward_m=float(q_positions[min(100,len(ref)-1),0]-q_positions[0,0]),
        first_2s_ref_forward_m=float(ref[min(100,len(ref)-1),0]-ref[0,0]),
        joints_mae_deg=float(joint_mae), minimum_pelvis_z_m=float(q_positions[:,2].min()),
        sustained_pelvis_below_035=bool(fallen.any()),
        stop_1s_path_m=float(stop_move), stop_1s_net_m=float(stop_net),
        missing_future_slots=int(missing), considered_future_slots=int(needed),
        missing_future_fraction=missing/needed,
        current_reference_missing_fraction=float(current_unavailable.mean()),
        onnx_ms_p50=float(np.median(warm_timing)), onnx_ms_p95=float(np.percentile(warm_timing,95)),
        onnx_over_20ms_fraction=float(np.mean(warm_timing>20)),
        cpu_loop_ms_p50=float(np.median(loop_ms[20:])), steps=len(ref),
    ), q_positions


def write_json(file, data):
    tmp = file.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2, allow_nan=False), encoding='utf-8')
    tmp.replace(file)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--threads', type=int, default=2)
    args = parser.parse_args()
    verify_configs()
    policies = [Controller(s, args.threads) for s in SPECS]
    sim = SonicMjSim(init_qpos=SONIC_DEFAULT_QPOS, headless=True, xml_path=str(XML))
    if not (sim.mj_model.nq == 36 and sim.mj_model.nv == 35 and sim.mj_model.nu == 29
            and np.isclose(sim.mj_model.opt.timestep, .001)):
        raise RuntimeError('Unexpected G1 model dimensions or timestep')

    if args.smoke:
        url='https://approchin.github.io/assets/ardy/representative-trajectories.zip'
        with urllib.request.urlopen(url, timeout=19) as response:
            with zipfile.ZipFile(io.BytesIO(response.read())) as z:
                q25=np.loadtxt(io.BytesIO(z.read('G1_H52_after_boundary.csv')),delimiter=',')
        q, v = resample(q25, sim.mj_model)
        verify_default_contract(q, v)
        for p in policies:
            stats,_=replay(sim,p,q,v,np.array([52,104,156,208,240]),np.ones(5),
                          [],156,'full')
            print('SMOKE',p.spec.name,json.dumps(stats),flush=True)
        print('SMOKE_OK',flush=True)
        return

    priority = ('G1_H8_whole_52lookahead_', 'G1_H52_patch_52lookahead_', 'G1_H52_', 'G1_H8_')
    def replay_order(path):
        return (next(i for i,prefix in enumerate(priority) if path.name.startswith(prefix)), path.name)
    references = sorted((ROOT/'references').glob('G1_H*.npz'), key=replay_order)
    if len(references) != 36:
        raise RuntimeError(f'Expected 36 reference inputs; got {len(references)}')
    out = ROOT/'comparison'
    out.mkdir(exist_ok=True)
    document = dict(
        policy_provenance=json.loads((ROOT/'model_provenance.json').read_text()),
        modes=dict(full='whole reference available',on_time='one committed block at its playback boundary',
                   timed='actual synchronized T4 compute time per block, floored by prerecorded command-ready time'),
        setup=dict(control_fps=50,sim_timestep_s=.001,ort_threads=args.threads,
                   reference_fps=25,following_old_turn_sign=False),
        cases=[],references=[],
    )
    for case_no, file in enumerate(references):
        info = json.loads(file.with_suffix('.json').read_text())
        config = next(label for prefix,label in CONFIGS.items() if file.name.startswith(prefix))
        if info.get('turn_direction_mujoco') != 'left_positive_y':
            raise ValueError(f'Mismatched turn coordinates in {file.name}')
        with np.load(file,allow_pickle=False) as a:
            q25 = a['qpos']
            q, vel = resample(q25,sim.mj_model)
            command_xy = commanded_path(info, q25)
            ends=a['block_ends_25']
            duration=a['generation_s']
            stop=int(a['stop_frame_25'])
        if case_no==0:
            verify_default_contract(q,vel)
            document['setup']['default_observation_parity']='exact float32 equality at four preselected frames'
        metadata=dict(id=file.stem,config=config,scenario=info['scenario'],seed=info['seed'],
                      events=info['events'],t4_window_s=duration.tolist(),block_ends_25=ends.tolist(),
                      root_ref_final_xy=q[-1,:2].tolist(),stop_frame_25=stop,
                      ardy_path_mae_m=info['mean_root_path_error_m'])
        metadata.update(inspect_reference(sim.mj_model,q,2*stop))
        document['references'].append(metadata)
        modes = ['on_time']
        if info['seed']==20261121:
            modes.append('full')
        if config in TIMED_CONFIGS and info['seed']==20261121:
            modes.append('timed')
        traces={'reference':q,'command_xy':command_xy} if config=='h8_52' and info['scenario']=='after_boundary' and info['seed']==20261121 else None
        for mode in modes:
            order=policies[::(-1 if case_no%2 else 1)]
            for policy in order:
                stats,actual = replay(sim,policy,q,vel,ends,duration,metadata['events'],stop,mode)
                cmd_error = np.linalg.norm(actual[:, :2]-command_xy,axis=1)
                stats['command_path_mae_m'] = float(cmd_error.mean())
                stats['command_path_final_m'] = float(cmd_error[-1])
                document['cases'].append(dict(ref=file.stem,config=config,scenario=info['scenario'],
                         seed=info['seed'],mode=mode,policy=policy.spec.name,**stats))
                if traces is not None:
                    traces[mode+'_'+policy.spec.name]=actual
        if traces is not None:
            np.savez_compressed(out/'h8_late_stop_trace.npz',stop_frame_25=stop,**traces)
        write_json(out/'sonic_comparison.json',document)
        print('CASE_DONE',case_no+1,len(references),file.stem,len(document['cases']),flush=True)
    if len(document['cases'])!=108:
        raise RuntimeError('Incomplete paired comparison')
    (out/'simulation_ready').touch()
    print('SONIC_COMPARISON_READY',len(document['references']),len(document['cases']),flush=True)


if __name__ == '__main__':
    main()
