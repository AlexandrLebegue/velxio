/** Parse provider-supplied think tags, including partial tags during streaming.
 * Fenced code is literal. This never enables raw HTML rendering. */
export function splitAgentThinking(text: string): { answer: string; thinking: string } {
  const answer: string[] = [],
    thinking: string[] = [];
  let inside = false,
    fence = '';
  for (let i = 0; i < text.length; ) {
    if (i === 0 || text[i - 1] === '\n') {
      const match = text.slice(i).match(/^ {0,3}(`{3,}|~{3,})/);
      if (match) {
        const token = match[1][0];
        if (!fence) fence = token;
        else if (fence === token) fence = '';
        (inside ? thinking : answer).push(match[0]);
        i += match[0].length;
        continue;
      }
    }
    if (!fence) {
      if (!inside && text.startsWith('<think>', i)) {
        inside = true;
        i += 7;
        continue;
      }
      if (inside && text.startsWith('</think>', i)) {
        inside = false;
        i += 8;
        continue;
      }
      const rest = text.slice(i);
      if ((inside ? '</think>' : '<think>').startsWith(rest)) break;
    }
    (inside ? thinking : answer).push(text[i++]);
  }
  return { answer: answer.join('').trim(), thinking: thinking.join('').trim() };
}

/** Display-only fallback for events saved before server-side path shortening. */
export function formatAgentToolText(text: string): string {
  return text
    .replace(
      /(?:\/?[\w.-]+\/)*agent\/[a-f\d]{32,64}\/sessions\/[a-f\d]{32}\/work(?:(\/)|(?=[\s<>"'`]|$))/gi,
      (_match, slash: string | undefined) => (slash ? '' : '.'),
    )
    .replace(/^<path>([^<]*)<\/path>(?=\r?\n<type>|$)/, (_match, path: string) => `File: ${path}`);
}
