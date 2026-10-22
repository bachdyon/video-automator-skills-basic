import type {FC} from 'react';
import {useCurrentFrame, useVideoConfig} from 'remotion';
import {FlyUpStaggerSubtitleLayer, ShortCaptionLayer} from './remotion';
import {getActiveSubtitleCue} from './timeline';
import type {SubtitleCue, SubtitleLayout, SubtitlePresetOptions, SubtitleTrack} from './types';

export type SubtitlePresetRendererProps = {
  cue: SubtitleCue;
  track: SubtitleTrack;
  layout: SubtitleLayout;
  zIndex: number;
  options: SubtitlePresetOptions;
};

export type SubtitlePresetRenderer = FC<SubtitlePresetRendererProps>;
export type SubtitlePresetRegistry = Record<string, SubtitlePresetRenderer>;

const numberOption = (options: SubtitlePresetOptions, key: string, fallback: number) => {
  const value = options[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
};

const stringOption = (options: SubtitlePresetOptions, key: string, fallback: string) => {
  const value = options[key];
  return typeof value === 'string' && value.trim() ? value : fallback;
};

export const DtPhuduPreset: SubtitlePresetRenderer = ({cue, layout, zIndex}) => (
  <ShortCaptionLayer
    pages={[cue]}
    zIndex={zIndex}
    style={
      layout === 'center'
        ? {captionAnchor: 0.5, captionOffsetPx: 0}
        : layout === 'top-safe'
          ? {captionAnchor: 0.2, captionOffsetPx: 0}
          : undefined
    }
  />
);

export const FlyUpStaggerPreset: SubtitlePresetRenderer = ({cue, layout, zIndex, options}) => (
  <FlyUpStaggerSubtitleLayer
    pages={[cue]}
    layout={layout}
    zIndex={zIndex}
    totalStaggerSeconds={numberOption(options, 'totalStaggerSeconds', 0.25)}
    flyDistancePx={numberOption(options, 'flyDistancePx', 160)}
    revealDurationFrames={numberOption(options, 'revealDurationFrames', 26)}
    exitDurationFrames={numberOption(options, 'exitDurationFrames', 0)}
    style={{
      safeWidth: numberOption(options, 'safeWidth', 900),
      fontFamily: stringOption(options, 'fontFamily', 'Arial Black, Arial, sans-serif'),
      fontSize: numberOption(options, 'fontSize', 62),
      letterSpacing: stringOption(options, 'letterSpacing', '-0.055em'),
      textColor: stringOption(options, 'textColor', '#fbf9ef'),
      wordGap: numberOption(options, 'wordGap', 18),
      rowGap: numberOption(options, 'rowGap', 12),
    }}
  />
);

export const DEFAULT_SUBTITLE_PRESET_REGISTRY: SubtitlePresetRegistry = {
  'dt-phudu': DtPhuduPreset,
  'fly-up-stagger': FlyUpStaggerPreset,
};

export type SubtitleTracksProps = {
  tracks: SubtitleTrack[];
  presets?: SubtitlePresetRegistry;
};

/** Render independent subtitle tracks, each with its own active cue and preset. */
export const SubtitleTracks: FC<SubtitleTracksProps> = ({
  tracks,
  presets = DEFAULT_SUBTITLE_PRESET_REGISTRY,
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const seconds = frame / fps;

  return (
    <>
      {tracks.map((track) => {
        const cue = getActiveSubtitleCue(track.cues, seconds);
        if (!cue) return null;
        const presetId = cue.preset ?? track.preset;
        const Preset = presets[presetId];
        if (!Preset) return null;
        return (
          <Preset
            key={`${track.id}-${cue.id ?? cue.start}`}
            cue={cue}
            track={track}
            layout={track.layout ?? 'lower-safe'}
            zIndex={track.zIndex ?? 30}
            options={{...track.presetOptions, ...cue.presetOptions}}
          />
        );
      })}
    </>
  );
};
