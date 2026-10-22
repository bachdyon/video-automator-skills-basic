export type CaptionToken = {
  id?: string;
  text: string;
  start?: number;
  end?: number;
};

export type SubtitleWord = {
  id?: string;
  text: string;
  start: number;
  end: number;
};

export type SubtitlePage = {
  id?: string;
  text: string;
  start: number;
  end: number;
  words: SubtitleWord[];
  /** Zero-based word indexes after which the renderer inserts a line break. */
  lineBreakAfter?: number[];
};

export type ShortCaptionStyle = {
  safeWidth: number;
  captionAnchor: number;
  captionOffsetPx: number;
  captionFontSize: number;
  lineHeight: number;
  fontFamily: string;
  fontWeight: number;
  textColor: string;
  activeTextColor: string;
  textShadow: string;
  maxWords: number;
  maxChars: number;
};

/** A named safe-area placement shared by subtitle presets. */
export type SubtitleLayout = 'top-safe' | 'center' | 'lower-safe';

export type SubtitlePresetOptions = Record<string, boolean | number | string | undefined>;

/** A timed page that can override the default preset selected by its track. */
export type SubtitleCue = SubtitlePage & {
  preset?: string;
  presetOptions?: SubtitlePresetOptions;
};

/**
 * An independently layered subtitle stream. Multiple tracks may be visible at
 * the same time, but a single track normally resolves to one active cue.
 */
export type SubtitleTrack = {
  id: string;
  cues: SubtitleCue[];
  preset: string;
  presetOptions?: SubtitlePresetOptions;
  layout?: SubtitleLayout;
  zIndex?: number;
};
