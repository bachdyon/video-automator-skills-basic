import type {SubtitlePage, SubtitleWord} from './types';

/** Pick the latest cue containing `seconds`, so an adjacent newer cue wins. */
export const getActiveSubtitleCue = <TCue extends SubtitlePage>(
  cues: readonly TCue[],
  seconds: number,
): TCue | null => {
  for (let index = cues.length - 1; index >= 0; index -= 1) {
    const cue = cues[index];
    if (seconds >= cue.start && seconds <= cue.end) return cue;
  }
  return null;
};

export const isSubtitleWordActive = (
  word: SubtitleWord,
  seconds: number,
  page: SubtitlePage,
  index: number,
) => {
  if (word.end > word.start) return seconds >= word.start && seconds <= word.end;
  const duration = Math.max(0.1, page.end - page.start);
  const activeIndex = Math.min(
    page.words.length - 1,
    Math.max(0, Math.floor(((seconds - page.start) / duration) * page.words.length)),
  );
  return index === activeIndex;
};
