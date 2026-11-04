"""Presentation-only path shortening; native tool inputs/results stay intact."""
import re


def display_text(text, workspace):
    text=str(text)
    for root in sorted({str(workspace.resolve()),str(workspace.resolve()).lstrip('/')},key=len,reverse=True):
        text=text.replace(root+'/', '')
        text=re.sub(re.escape(root)+r'''(?=$|[\s<>"'`])''','.',text)
    return text
