import type {CaptionToken, SubtitlePage, SubtitleWord} from './types';

const LEADING_TOKEN_CHARS = '"\'([“‘«';
const SPLIT_PUNCTUATION = new Set([',', '.', '!', '?', ';', ':', '…']);

const isCapitalizedWord = (text: string) => {
  const token = text.trim().replace(new RegExp(`^[${LEADING_TOKEN_CHARS}]+`), '');
  if (!token) return false;
  const first = token[0];
  return Boolean(first && first.toLocaleUpperCase() === first && first.toLocaleLowerCase() !== first);
};

const endsWithSplitPunctuation = (text: string) => {
  const token = text.trim().replace(/["')\]}»”]+$/u, '');
  return Boolean(token && SPLIT_PUNCTUATION.has(token[token.length - 1]));
};

const isHyphenContinuation = (text: string) => /^[-‐‑‒–—]/u.test(text.trim());
const endsWithHyphen = (text: string) => /[-‐‑‒–—]$/u.test(text.trim());

const normalizeWord = (token: CaptionToken, index: number): SubtitleWord => {
  const start = Number.isFinite(token.start) ? Number(token.start) : 0;
  const end = Number.isFinite(token.end) ? Number(token.end) : start;
  return {
    id: token.id ?? `W_${String(index + 1).padStart(4, '0')}`,
    text: token.text.trim(),
    start,
    end: Math.max(start, end),
  };
};

export type SplitCaptionOptions = {
  maxWords?: number;
  maxChars?: number;
  maxWordsPerLine?: number;
  splitOnCapitalized?: boolean;
  splitOnPunctuation?: boolean;
  preferredBreakBefore?: readonly string[];
};

/** Join STT fragments such as `type` + `-C` before counting words or wrapping. */
export const mergeCaptionContinuations = (words: SubtitleWord[]) => {
  const merged: SubtitleWord[] = [];
  words.forEach((word) => {
    const previous = merged[merged.length - 1];
    if (previous && (isHyphenContinuation(word.text) || endsWithHyphen(previous.text))) {
      previous.text += word.text;
      previous.end = Math.max(previous.end, word.end);
      return;
    }
    merged.push({...word});
  });
  return merged;
};

export const splitCaptionTokens = (
  tokens: CaptionToken[],
  options: SplitCaptionOptions = {},
): SubtitlePage[] => {
  const maxWords = options.maxWords ?? 7;
  const maxChars = options.maxChars ?? 34;
  const maxWordsPerLine = options.maxWordsPerLine;
  const splitOnCapitalized = options.splitOnCapitalized ?? true;
  const splitOnPunctuation = options.splitOnPunctuation ?? true;
  const preferredBreakBefore = new Set(
    (options.preferredBreakBefore ?? ['cho', 'để', 'nhưng', 'vì', 'nên']).map((word) => word.toLocaleLowerCase()),
  );
  const pages: SubtitlePage[] = [];
  let current: SubtitleWord[] = [];

  const pageText = (words: SubtitleWord[]) => words.map((word) => word.text).join(' ').trim();
  const flush = () => {
    if (!current.length) return;
    pages.push({
      id: `PAGE_${String(pages.length + 1).padStart(4, '0')}`,
      text: pageText(current),
      start: current[0].start,
      end: current[current.length - 1].end || current[current.length - 1].start,
      words: current,
      lineBreakAfter:
        maxWordsPerLine && current.length > maxWordsPerLine
          ? [maxWordsPerLine - 1]
          : undefined,
    });
    current = [];
  };

  const normalizedWords = mergeCaptionContinuations(
    tokens.filter((token) => token.text.trim()).map(normalizeWord),
  );

  normalizedWords.forEach((word) => {
    if (splitOnCapitalized && current.length && isCapitalizedWord(word.text)) flush();

    const lowerWord = word.text.toLocaleLowerCase().replace(/^["'“‘«]+/u, '');
    const preferredBoundary =
      current.length >= Math.max(5, maxWords - 1) && preferredBreakBefore.has(lowerWord);
    if (preferredBoundary) flush();

    const candidate = [...current, word];
    if (current.length && (candidate.length > maxWords || pageText(candidate).length > maxChars)) flush();

    current.push(word);
    if (splitOnPunctuation && endsWithSplitPunctuation(word.text)) flush();
  });

  flush();
  return pages;
};

export const splitCaptionText = (text: string, options: SplitCaptionOptions = {}) =>
  splitCaptionTokens(text.match(/\S+/gu)?.map((token) => ({text: token})) ?? [], options);
