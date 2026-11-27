from collections import defaultdict
from hashlib import sha1
from html.parser import HTMLParser
import json
import re


EDITABLE_TAGS = {'p', 'h2', 'h3', 'h4', 'h5', 'h6'}
VOID_TAGS = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
             'meta', 'param', 'source', 'track', 'wbr'}


class TextBlocks(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=False)
        self.html = html
        self.line_starts = [0, *(match.end() for match in re.finditer('\n', html))]
        self.stack = []
        self.start = 0
        self.spans = defaultdict(list)
        self.feed(html)
        self.close()

    def position(self):
        line, column = self.getpos()
        return self.line_starts[line - 1] + column

    def handle_starttag(self, tag, attrs):
        if tag in VOID_TAGS:
            return
        if not self.stack:
            self.start = self.position()
        self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        if tag not in self.stack:
            return
        closer = len(self.stack) - 1 - self.stack[::-1].index(tag)
        del self.stack[closer:]
        if not self.stack and tag in EDITABLE_TAGS:
            end = self.html.index('>', self.position()) + 1
            self.spans[self.html[self.start:end]].append(self.start + len(tag) + 1)


def note_editor_payload(raw, render):
    """Map whole Markdown blocks to the identical top-level rendered text blocks."""
    source = raw.decode('utf-8')
    parts = re.split(r'(\r?\n(?:[ \t]*\r?\n)+)', source)
    html = render(source)
    available = TextBlocks(html).spans
    sources = defaultdict(list)
    for index in range(0, len(parts), 2):
        part = parts[index]
        if not part.strip() or part.lstrip().startswith('<'):
            continue
        fragment = render(part).strip()
        if fragment in available:
            sources[fragment].append(index)

    # Count mismatches can arise from Markdown reference definitions or raw HTML;
    # keep those blocks editable through the source file instead.
    marks = [(offset, index)
             for fragment, indices in sources.items()
             if len(indices) == len(available[fragment])
             for offset, index in zip(available[fragment], indices)]
    for offset, index in sorted(marks, reverse=True):
        html = html[:offset] + f' data-edit-part="{index}"' + html[offset:]

    sha = sha1(f'blob {len(raw)}\0'.encode() + raw).hexdigest()
    payload = json.dumps({'parts': parts, 'sha': sha}, ensure_ascii=False)
    return html, payload.replace('<', '\\u003c')
