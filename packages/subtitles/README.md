# `@video-agent/subtitles`

Reusable caption primitives for the video-agent Remotion jobs.

The default preset is `DT_PHUDU_SHORT_CAPTION_STYLE`: DT Phudu bold, bright yellow text, a strong dark shadow, no background box, and a caption anchor at 65% of the canvas plus 100px. Pages target 5-6 words, allow up to 7 to preserve a complete phrase, and use punctuation-first splitting within 34 characters.

```tsx
import {
  DT_PHUDU_SHORT_CAPTION_STYLE,
  ShortCaptionLayer,
  splitCaptionTokens,
} from '@video-agent/subtitles';

const pages = splitCaptionTokens(tokens, {
  maxWords: DT_PHUDU_SHORT_CAPTION_STYLE.maxWords,
  maxChars: DT_PHUDU_SHORT_CAPTION_STYLE.maxChars,
});

return <ShortCaptionLayer pages={pages} />;
```

`tokens` use `{text, start, end}` in seconds. Pure splitting utilities are available from `@video-agent/subtitles/split`; the Remotion layer is available from `@video-agent/subtitles/remotion`.

## Preset subtitle tracks

Use `SubtitleTracks` when one composition needs more than one subtitle treatment. Each track owns its own cue timeline, placement and z-index. A cue may override its track preset.

```tsx
import {SubtitleTracks} from '@video-agent/subtitles';

<SubtitleTracks
  tracks={[
    {
      id: 'narration',
      preset: 'dt-phudu',
      layout: 'lower-safe',
      zIndex: 30,
      cues: narrationPages,
    },
    {
      id: 'hook',
      preset: 'fly-up-stagger',
      layout: 'center',
      zIndex: 40,
      presetOptions: {
        totalStaggerSeconds: 0.25,
        flyDistancePx: 160,
      },
      cues: hookPages,
    },
  ]}
/>
```

For one fly-up layer without a track registry, use `FlyUpStaggerSubtitleLayer` directly. It reveals each word from below the resting baseline with deterministic Remotion frame timing. The default stagger spans `0.25` seconds from the first word to the last, and the default travel is `160` px.
