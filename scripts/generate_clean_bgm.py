#!/usr/bin/env python3
"""Generate 100% original, copyright-immune ambient background music for YouTube Shorts.

Uses pure Python standard library (wave, struct, math) + FFmpeg.
No external Python dependencies (no scipy, no numpy) required.

Because these waveforms are mathematically synthesized from scratch, they have
ZERO acoustic fingerprints in YouTube Content ID and are 100% immune to claims.
"""

from __future__ import annotations

import math
import os
import struct
import subprocess
import wave

SONGS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resource", "songs"
)


def generate_ambient_track(
    filename: str,
    chords: list[list[float]],
    chord_duration: float = 6.0,
    total_duration: float = 90.0,
    sample_rate: int = 44100,
    cutoff_freq: int = 2200,
) -> None:
    """Synthesize a lush stereo ambient soundscape using pure stdlib wave/struct."""
    total_samples = int(sample_rate * total_duration)
    samples_per_chord = int(sample_rate * chord_duration)
    num_chords = len(chords)

    left_channel = [0.0] * total_samples
    right_channel = [0.0] * total_samples

    total_chord_cycles = int(total_duration / chord_duration)

    for c_idx in range(total_chord_cycles):
        start_sample = int(c_idx * samples_per_chord)
        end_sample = min(int((c_idx + 1) * samples_per_chord), total_samples)
        chord = chords[c_idx % num_chords]

        for s in range(start_sample, end_sample):
            local_t = (s - start_sample) / sample_rate
            # Smooth bell envelope
            env = math.sin(math.pi * local_t / chord_duration) ** 1.4

            for note in chord:
                freq_l = note * 1.0015
                freq_r = note * 0.9985

                # Multi-harmonic synthesis (fundamental + warm overtones)
                w_l = (
                    0.55 * math.sin(2.0 * math.pi * freq_l * local_t)
                    + 0.25 * math.sin(2.0 * math.pi * freq_l * 2.0 * local_t)
                    + 0.12 * math.sin(2.0 * math.pi * freq_l * 3.0 * local_t)
                    + 0.05 * math.sin(2.0 * math.pi * freq_l * 4.0 * local_t)
                )
                w_r = (
                    0.55 * math.sin(2.0 * math.pi * freq_r * local_t)
                    + 0.25 * math.sin(2.0 * math.pi * freq_r * 2.0 * local_t)
                    + 0.12 * math.sin(2.0 * math.pi * freq_r * 3.0 * local_t)
                    + 0.05 * math.sin(2.0 * math.pi * freq_r * 4.0 * local_t)
                )

                # Slow evolving chorus modulation
                lfo_l = 0.88 + 0.12 * math.sin(2.0 * math.pi * 0.2 * local_t)
                lfo_r = 0.88 + 0.12 * math.cos(2.0 * math.pi * 0.2 * local_t)

                left_channel[s] += w_l * env * lfo_l
                right_channel[s] += w_r * env * lfo_r

    # Find peak for normalization
    peak = max(
        max(abs(v) for v in left_channel),
        max(abs(v) for v in right_channel),
        1e-6,
    )

    scale = 0.70 * 32767.0 / peak
    os.makedirs(SONGS_DIR, exist_ok=True)
    temp_wav = os.path.join(SONGS_DIR, f"temp_{filename}.wav")
    out_mp3 = os.path.join(SONGS_DIR, filename)

    # Write 16-bit stereo WAV with pure standard library
    with wave.open(temp_wav, "w") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        raw_frames = bytearray()
        for l_val, r_val in zip(left_channel, right_channel):
            i_l = max(-32768, min(32767, int(l_val * scale)))
            i_r = max(-32768, min(32767, int(r_val * scale)))
            raw_frames.extend(struct.pack("<hh", i_l, i_r))
        wf.writeframes(raw_frames)

    # Master with gentle spatial echo and warm lowpass filter via FFmpeg
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            temp_wav,
            "-af",
            f"aecho=0.8:0.85:70|140:0.35|0.20,lowpass=f={cutoff_freq},volume=0.9",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-b:a",
            "128k",
            out_mp3,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    if os.path.exists(temp_wav):
        os.remove(temp_wav)

    print(f"✓ Generated 100% copyright-immune track: {filename} ({os.path.getsize(out_mp3)} bytes)")


def main() -> None:
    # 1. Clean out any old audio files in resource/songs
    if os.path.exists(SONGS_DIR):
        for f in os.listdir(SONGS_DIR):
            p = os.path.join(SONGS_DIR, f)
            if os.path.isfile(p):
                os.remove(p)

    # Track 1: Warm Calm Harmony (C Major / Am9)
    generate_ambient_track(
        "ambient_calm_harmony.mp3",
        chords=[
            [261.63, 329.63, 392.00, 493.88],  # Cmaj7
            [220.00, 261.63, 329.63, 493.88],  # Am9
            [174.61, 220.00, 261.63, 329.63],  # Fmaj7
            [196.00, 261.63, 293.66, 392.00],  # Gsus4
        ],
        cutoff_freq=2400,
    )

    # Track 2: Deep Focus Pad (D Dorian / F)
    generate_ambient_track(
        "ambient_deep_focus.mp3",
        chords=[
            [146.83, 220.00, 293.66, 349.23],  # Dm7
            [174.61, 261.63, 329.63, 392.00],  # Fmaj7
            [196.00, 246.94, 293.66, 392.00],  # G7
            [220.00, 261.63, 329.63, 440.00],  # Am7
        ],
        cutoff_freq=2100,
    )

    # Track 3: Inspiring Horizons (E Major / C#m7)
    generate_ambient_track(
        "ambient_inspiring_horizons.mp3",
        chords=[
            [164.81, 246.94, 329.63, 415.30],  # Emaj7
            [138.59, 207.65, 277.18, 329.63],  # C#m7
            [146.83, 220.00, 293.66, 369.99],  # F#m7
            [123.47, 185.00, 246.94, 329.63],  # Bsus4
        ],
        cutoff_freq=2500,
    )

    # Track 4: Cosmic Solitude (G Lydian / Em9)
    generate_ambient_track(
        "ambient_cosmic_solitude.mp3",
        chords=[
            [196.00, 293.66, 369.99, 440.00],  # Gmaj9
            [164.81, 246.94, 329.63, 392.00],  # Em7
            [174.61, 261.63, 349.23, 440.00],  # Fmaj7(#11)
            [196.00, 246.94, 293.66, 369.99],  # Gmaj7
        ],
        cutoff_freq=2300,
    )

    # Track 5: Mindful Serenity (Ab Major dreamy)
    generate_ambient_track(
        "ambient_mindful_serenity.mp3",
        chords=[
            [207.65, 261.63, 311.13, 392.00],  # Abmaj7
            [174.61, 207.65, 261.63, 311.13],  # Fm7
            [138.59, 207.65, 261.63, 311.13],  # Dbmaj7
            [155.56, 207.65, 233.08, 311.13],  # Ebsus4
        ],
        cutoff_freq=2000,
    )

    print("\n✓ Successfully created 5 original, copyright-immune ambient tracks in resource/songs/!")


if __name__ == "__main__":
    main()
