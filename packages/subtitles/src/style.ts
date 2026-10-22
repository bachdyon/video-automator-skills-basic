import type {ShortCaptionStyle} from './types';

/** The caption contract captured from the finished product-review video. */
export const DT_PHUDU_SHORT_CAPTION_STYLE: Readonly<ShortCaptionStyle> = {
  safeWidth: 880,
  captionAnchor: 0.65,
  captionOffsetPx: 100,
  captionFontSize: 46,
  lineHeight: 1.25,
  fontFamily: 'DT Phudu',
  fontWeight: 700,
  textColor: '#FFE94A',
  activeTextColor: '#FFF36A',
  textShadow: '0 3px 0 #2B1F24, 0 6px 12px rgba(0,0,0,0.72)',
  maxWords: 7,
  maxChars: 34,
};

export const captionTopPx = (
  canvasHeight: number,
  style: Pick<ShortCaptionStyle, 'captionAnchor' | 'captionOffsetPx'> = DT_PHUDU_SHORT_CAPTION_STYLE,
) => canvasHeight * style.captionAnchor + style.captionOffsetPx;

export const fitShortCaptionFontSize = (
  textLength: number,
  baseFontSize = DT_PHUDU_SHORT_CAPTION_STYLE.captionFontSize,
  safeWidth = DT_PHUDU_SHORT_CAPTION_STYLE.safeWidth,
) => {
  const charWidthRatio = 0.58;
  const twoLineCapacity = Math.floor(safeWidth / (baseFontSize * charWidthRatio)) * 2;
  if (textLength <= twoLineCapacity) return baseFontSize;
  return Math.max(40, Math.round(baseFontSize * Math.sqrt(twoLineCapacity / textLength)));
};
