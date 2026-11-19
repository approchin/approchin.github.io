"""Build the two editable Markdown project articles for GitHub Pages."""

from html import escape
from pathlib import Path
import json
import re
import shutil

from markdown import markdown

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"


def render_article(source, table_label, base=""):
    content = (ROOT / source).read_text(encoding="utf-8")
    content = re.sub(r'(?<=["(])assets/', f"{base}assets/", content)
    body = markdown(
        content,
        extensions=["attr_list", "tables", "fenced_code", "pymdownx.arithmatex"],
        extension_configs={"pymdownx.arithmatex": {"generic": True}},
    )
    return re.sub(
        r"(<table>.*?</table>)",
        lambda table: (
            f'<div class="table-scroll" role="region" aria-label="{escape(table_label)}" tabindex="0">'
            + table.group(0) + '</div>'
        ),
        body,
        flags=re.S,
    )


def verified_asset(path):
    assert (ROOT / path).is_file(), path
    return path


def build_supermimic():
    clips = json.loads((ROOT / "clips.json").read_text(encoding="utf-8"))
    assert len(clips) == 8 and len({clip["id"] for clip in clips}) == len(clips)
    base = "../"
    for clip in clips:
        for kind, suffix in (("video", "mp4"), ("poster", "jpg")):
            asset = clip[kind]
            assert re.fullmatch(rf"0[2-9]_[a-z_]+\.{suffix}", asset)
            verified_asset(f"assets/media/{asset}")
    hero = next(clip for clip in clips if clip["id"] == "04")
    cards = []
    for clip in clips:
        title = escape(clip["label"], quote=True)
        current = ' aria-current="true"' if clip == hero else ""
        cards.append(
            f'<li><a data-clip-id="{clip["id"]}" data-title="{title}" '
            f'data-poster="{base}assets/media/{clip["poster"]}" '
            f'data-metric="{clip["seconds"]:.2f} 秒 · 关节 MAE {clip["mae"]:.2f}°" '
            f'href="{base}assets/media/{clip["video"]}"{current}>'
            f'<span class="option-id">{clip["id"]}</span><strong>{title}</strong>'
            f'<span class="option-meta">{clip["seconds"]:.2f} 秒</span></a></li>'
        )
    write_page(DIST / "supermimic-pm01" / "index.html", {
        "PROJECT": "supermimic",
        "PROJECT_NAME": "SuperMimic-PM01",
        "DISPLAY_NAME": "SuperMimic",
        "DESCRIPTION": "SuperMimic 在众擎 PM01 上的适配记录：65k 仿真对照、训练与推理、数学推导和实验分析。",
        "TITLE": "SuperMimic-PM01 · 从参考动作到闭环跟踪",
        "BASE": base,
        "DECK": "给众擎 PM01 一段参考动作，观察它如何跟上。下面从 65k 策略的一段仿真对照讲起，串起训练、推理和实验结果。",
        "METHOD_URL": "#training",
        "METHOD_LABEL": "训练",
        "ASSET_CREDIT": "../assets/sonic/licenses/ENGINEAI-NATIVE-SDK-BSD-3-CLAUSE.txt",
        "VIDEO_WIDTH": "1280",
        "VIDEO_HEIGHT": "480",
        "POLICY_LABEL": "策略轨迹",
        "VARIANT_CONTROLS": "",
        "PROTOCOL": "65k · CPU MuJoCo / FP32 ONNX · 仿真",
        "CLIP_COUNT": "8 段",
        "FEATURE_VIDEO": base + "assets/media/" + hero["video"],
        "FEATURE_POSTER": base + "assets/media/" + hero["poster"],
        "FEATURE_LABEL": escape(hero["label"], quote=True),
        "FEATURE_METRICS": f'{hero["seconds"]:.2f} 秒 · 关节 MAE {hero["mae"]:.2f}°',
        "CLIP_LINKS": "\n              ".join(cards),
        "ARTICLE": render_article("article.md", "固定 200 段仿真复测结果", base),
    })


def build_sonic():
    clips = json.loads((ROOT / "sonic-clips.json").read_text(encoding="utf-8"))
    assert len(clips) == 7 and len({clip["id"] for clip in clips}) == len(clips)
    base = "../"
    hero = next(clip for clip in clips if clip["reference"] == "full_turn_dance")
    cards = []
    for clip in clips:
        title = escape(clip["label"], quote=True)
        current = ' aria-current="true"' if clip == hero else ""
        links = {}
        for variant in ('a', 'b'):
            for role, suffix in (("video", "mp4"), ("poster", "jpg")):
                name = clip[variant][role]
                assert re.fullmatch(rf"[a-z_]+-{variant}\.{suffix}", name), name
                links[variant, role] = base + verified_asset(f"assets/sonic/media/{name}")
        cards.append(
            f'<li><a data-clip-id="{clip["id"]}" data-title="{title}" '
            f'data-metric="{clip["seconds"]:.2f} 秒" '
            f'href="{links["a", "video"]}" data-poster="{links["a", "poster"]}" '
            f'data-video-a="{links["a", "video"]}" data-video-b="{links["b", "video"]}" '
            f'data-poster-b="{links["b", "poster"]}"{current}>'
            f'<span class="option-id">{clip["id"]}</span><strong>{title}</strong>'
            f'<span class="option-meta">{clip["seconds"]:.2f} 秒</span></a></li>'
        )
    write_page(DIST / 'sonic-pm01' / 'index.html', {
        "PROJECT": "sonic",
        "PROJECT_NAME": "SONIC-PM01",
        "DISPLAY_NAME": "SONIC",
        "DESCRIPTION": "SONIC 从 G1 适配到众擎 PM01：同参考 A/B 仿真回放、适配公式和固定 500 段评测。",
        "TITLE": "SONIC-PM01 · 同一个动作，两种微调",
        "BASE": base,
        "DECK": "把 G1 上的 SONIC 策略迁到众擎 PM01。对比两种微调方式：固定参考编码器，或者让它和动作解码器一起学习。",
        "METHOD_URL": "#adaptation",
        "METHOD_LABEL": "适配与训练",
        "ASSET_CREDIT": "../assets/sonic/licenses/ENGINEAI-NATIVE-SDK-BSD-3-CLAUSE.txt",
        "VIDEO_WIDTH": "1386",
        "VIDEO_HEIGHT": "438",
        "POLICY_LABEL": "策略 A 轨迹",
        "VARIANT_CONTROLS": (
            '<div class="variant-strip">'
            '<div class="variant-controls" role="group" aria-label="切换 28k 策略方案">'
            '<button type="button" data-variant="a" aria-pressed="true">A · 固定编码器</button>'
            '<button type="button" data-variant="b" aria-pressed="false">B · 微调编码器</button>'
            '</div><span class="variant-note">两组都微调动作解码器</span></div>'
        ),
        "PROTOCOL": "28k · PhysX 物理仿真 · MuJoCo 回放",
        "CLIP_COUNT": "7 组",
        "FEATURE_VIDEO": base + f'assets/sonic/media/{hero["a"]["video"]}',
        "FEATURE_POSTER": base + f'assets/sonic/media/{hero["a"]["poster"]}',
        "FEATURE_LABEL": escape(hero["label"], quote=True),
        "FEATURE_METRICS": f'{hero["seconds"]:.2f} 秒',
        "CLIP_LINKS": "\n              ".join(cards),
        "ARTICLE": render_article("sonic-article.md", "SONIC-PM01 的方案对照"),
    })


def write_page(path, fields, template="page.html"):
    page = (ROOT / template).read_text(encoding="utf-8")
    for marker, fragment in fields.items():
        page = page.replace("{{" + marker + "}}", fragment)
    assert re.search(r"\{\{[A-Z_]+\}\}", page) is None
    path.parent.mkdir(exist_ok=True, parents=True)
    path.write_text(page, encoding="utf-8")
    print(f"Built {path.relative_to(ROOT)}")


def build_catalog():
    projects = json.loads((ROOT / "projects.json").read_text(encoding="utf-8"))
    rows = []
    for project in projects:
        slug = project["slug"]
        assert re.fullmatch(r"[a-z0-9-]+", slug)
        assert (DIST / slug / "index.html").is_file()
        rows.append(
            f'<li><a class="project-row" href="{slug}/index.html">'
            f'<span><strong>{escape(project["title"])}</strong>'
            f'<span class="project-summary">{escape(project["description"])}</span></span>'
            '<svg aria-hidden="true" width="23" height="23" viewBox="0 0 24 24">'
            '<path d="M4 12h15m-6-6 6 6-6 6" fill="none" stroke="currentColor" '
            'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg></a></li>'
        )
    write_page(DIST / "index.html", {"PROJECT_ROWS": "\n      ".join(rows)}, template="home.html")


def build():
    DIST.mkdir(exist_ok=True)
    shutil.copytree(ROOT / "assets", DIST / "assets", dirs_exist_ok=True)
    build_supermimic()
    build_sonic()
    build_catalog()
    (DIST / ".nojekyll").touch()


if __name__ == "__main__":
    build()
