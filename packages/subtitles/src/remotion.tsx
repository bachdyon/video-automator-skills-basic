import {Fragment} from 'react';
import type {CSSProperties, FC} from 'react';
import {motion} from 'motion/react';
import {Easing, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {
  DT_PHUDU_SHORT_CAPTION_STYLE,
  captionTopPx,
  fitShortCaptionFontSize,
} from './style';
import type {ShortCaptionStyle, SubtitlePage} from './types';
import {getActiveSubtitleCue, isSubtitleWordActive} from './timeline';

export type ShortCaptionLayerProps = {
  pages: SubtitlePage[];
  style?: Partial<ShortCaptionStyle>;
  zIndex?: number;
  horizontalInset?: number;
};

/** Render one punctuation-first caption page with no background box. */
export const ShortCaptionLayer: FC<ShortCaptionLayerProps> = ({
  pages,
  style: styleOverrides,
  zIndex = 30,
  horizontalInset = 70,
}) => {
  const frame = useCurrentFrame();
  const {fps, height} = useVideoConfig();
  const seconds = frame / fps;
  const style = {...DT_PHUDU_SHORT_CAPTION_STYLE, ...styleOverrides};
  const page = getActiveSubtitleCue(pages, seconds);
  if (!page) return null;

  const words = page.words.length ? page.words : page.text.split(/\s+/u).map((text, index) => ({
    id: `${page.id ?? page.start}-${index}`,
    text,
    start: page.start,
    end: page.end,
  }));
  const fontSize = fitShortCaptionFontSize(page.text.length, style.captionFontSize, style.safeWidth);
  const containerStyle: CSSProperties = {
    position: 'absolute',
    top: captionTopPx(height, style),
    left: horizontalInset,
    right: horizontalInset,
    maxWidth: style.safeWidth,
    margin: '0 auto',
    translate: '0 -50%',
    display: 'flex',
    justifyContent: 'center',
    alignItems: 'center',
    flexWrap: 'wrap',
    columnGap: 10,
    rowGap: 4,
    padding: '4px 8px',
    zIndex,
    color: style.textColor,
    fontFamily: style.fontFamily,
    fontSize,
    fontWeight: style.fontWeight,
    lineHeight: style.lineHeight,
    textAlign: 'center',
    wordBreak: 'normal',
    overflowWrap: 'normal',
    whiteSpace: 'pre-wrap',
    background: 'transparent',
  };

  return (
    <div style={containerStyle} aria-label={page.text}>
      {words.map((word, index) => {
        const active = isSubtitleWordActive(word, seconds, page, index);
        return (
          <Fragment key={`${word.id ?? word.text}-${index}`}>
            {index > 0 && page.lineBreakAfter?.includes(index - 1) ? (
              <div style={{flexBasis: '100%', height: 0}} />
            ) : null}
            <span
              style={{
                display: 'inline-block',
                flexShrink: 0,
                color: active ? style.activeTextColor : style.textColor,
                textShadow: style.textShadow,
                scale: active ? 1.04 : 1,
                translate: active ? '0px -2px' : '0px 0px',
                whiteSpace: 'nowrap',
              }}
            >
              {word.text}
            </span>
          </Fragment>
        );
      })}
    </div>
  );
};

export type FlyUpStaggerSubtitleStyle = {
  safeWidth: number;
  fontFamily: string;
  fontSize: number;
  fontWeight: number;
  letterSpacing: string;
  lineHeight: number;
  textColor: string;
  wordGap: number;
  rowGap: number;
};

export const FLY_UP_STAGGER_SUBTITLE_STYLE: Readonly<FlyUpStaggerSubtitleStyle> = {
  safeWidth: 900,
  fontFamily: 'Arial Black, Arial, sans-serif',
  fontSize: 62,
  fontWeight: 900,
  letterSpacing: '-0.055em',
  lineHeight: 1.25,
  textColor: '#fbf9ef',
  wordGap: 18,
  rowGap: 12,
};

export type FlyUpStaggerSubtitleLayerProps = {
  pages: SubtitlePage[];
  style?: Partial<FlyUpStaggerSubtitleStyle>;
  zIndex?: number;
  horizontalInset?: number;
  /** Delay from the first word's launch to the last word's launch. */
  totalStaggerSeconds?: number;
  /** Vertical distance below the resting baseline at the start of each word. */
  flyDistancePx?: number;
  revealDurationFrames?: number;
  exitDurationFrames?: number;
  layout?: 'top-safe' | 'center' | 'lower-safe';
};

const layoutTopPx = (height: number, layout: FlyUpStaggerSubtitleLayerProps['layout']) => {
  if (layout === 'top-safe') return height * 0.2;
  if (layout === 'lower-safe') return height * 0.7;
  return height * 0.56;
};

/**
 * Render a timed subtitle page by launching every word upward in sequence.
 * Motion elements are driven solely by Remotion frames for deterministic output.
 */
export const FlyUpStaggerSubtitleLayer: FC<FlyUpStaggerSubtitleLayerProps> = ({
  pages,
  style: styleOverrides,
  zIndex = 30,
  horizontalInset = 70,
  totalStaggerSeconds = 0.25,
  flyDistancePx = 160,
  revealDurationFrames = 26,
  exitDurationFrames = 0,
  layout = 'lower-safe',
}) => {
  const frame = useCurrentFrame();
  const {fps, height} = useVideoConfig();
  const page = getActiveSubtitleCue(pages, frame / fps);
  if (!page) return null;

  const style = {...FLY_UP_STAGGER_SUBTITLE_STYLE, ...styleOverrides};
  const words = page.words.length
    ? page.words
    : page.text.split(/\s+/u).map((text, index) => ({
        id: `${page.id ?? page.start}-${index}`,
        text,
        start: page.start,
        end: page.end,
      }));
  const cueStartFrame = page.start * fps;
  const cueEndFrame = page.end * fps;
  const staggerFrames = totalStaggerSeconds * fps;
  const intervals = Math.max(1, words.length - 1);

  return (
    <div
      aria-label={page.text}
      style={{
        position: 'absolute',
        top: layoutTopPx(height, layout),
        left: horizontalInset,
        right: horizontalInset,
        maxWidth: style.safeWidth,
        margin: '0 auto',
        translate: '0 -50%',
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        flexWrap: 'wrap',
        columnGap: style.wordGap,
        rowGap: style.rowGap,
        zIndex,
        color: style.textColor,
        fontFamily: style.fontFamily,
        fontSize: style.fontSize,
        fontWeight: style.fontWeight,
        letterSpacing: style.letterSpacing,
        lineHeight: style.lineHeight,
        textAlign: 'center',
      }}
    >
      {words.map((word, index) => {
        const wordStart = cueStartFrame + (index / intervals) * staggerFrames;
        const reveal = interpolate(frame, [wordStart, wordStart + revealDurationFrames], [0, 1], {
          extrapolateLeft: 'clamp',
          extrapolateRight: 'clamp',
          easing: Easing.bezier(0.22, 1, 0.36, 1),
        });
        const flyUp = interpolate(frame, [wordStart, wordStart + revealDurationFrames], [flyDistancePx, 0], {
          extrapolateLeft: 'clamp',
          extrapolateRight: 'clamp',
          easing: Easing.bezier(0.22, 1, 0.36, 1),
        });
        const exit = exitDurationFrames
          ? interpolate(frame, [cueEndFrame - exitDurationFrames, cueEndFrame], [0, 1], {
              extrapolateLeft: 'clamp',
              extrapolateRight: 'clamp',
              easing: Easing.bezier(0.4, 0, 1, 1),
            })
          : 0;

        return (
          <Fragment key={`${word.id ?? word.text}-${index}`}>
            {index > 0 && page.lineBreakAfter?.includes(index - 1) ? (
              <div style={{flexBasis: '100%', height: 0}} />
            ) : null}
            <motion.span
              style={{
                display: 'inline-block',
                opacity: reveal * (1 - exit),
                translate: `0 ${flyUp}px`,
                scale: 0.98 + reveal * 0.02,
                willChange: frame >= wordStart && frame < wordStart + revealDurationFrames ? 'transform, opacity' : 'auto',
                whiteSpace: 'nowrap',
              }}
            >
              {word.text}
            </motion.span>
          </Fragment>
        );
      })}
    </div>
  );
};
