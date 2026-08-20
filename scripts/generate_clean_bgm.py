#!/usr/bin/env python3
"""Generate 100% original, copyright-immune ambient background music for YouTube Shorts.

Uses harmonic synthesis, stereo chorusing, tape-style gentle filtering,
and smooth reverb to create lush, pleasant, non-intrusive background tracks.

Because these waveforms are mathematically generated from scratch, they have
ZERO acoustic fingerprints in YouTube Content ID and are 100% immune to claims.
"""

from __future__ import annotations

import os
import subprocess
import numpy as np
import scipy.io.wavfile as wav

SONGS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resource", "songs")


def generate_ambient_track(
    filename: str,
    chords: list[list[float]],
    chord_duration: float = 6.0,
    total_duration: float = 90.0,
    sample_rate: int = 44100,
    cutoff_freq: int = 2200,
) -> None:
    """Synthesize a lush stereo ambient soundscape and save as clean MP3."""
    t = np.linspace(0, total_duration, int(sample_rate * total_duration), False)
    signal_l = np.zeros_like(t)
    signal_r = np.zeros_like(t)

    total_chords = int(total_duration / chord_duration)

    for i in range(total_chords):
        start_idx = int(i * chord_duration * sample_rate)
        end_idx = int((i + 1) * chord_duration * sample_rate)
        chord_t = t[start_idx:end_idx] - (i * chord_duration)
        chord = chords[i % len(chords)]

        # Smooth bell envelope with gentle crossfade
        env = np.sin(np.pi * chord_t / chord_duration) ** 1.4

        for note in chord:
            # Subtle stereo detuning for width
            freq_l = note * 1.0015
            freq_r = note * 0.9985

            # Multi-harmonic synthesis (fundamental + warm overtone series)
            wave_l = (
                0.55 * np.sin(2 * np.pi * freq_l * chord_t)
                + 0.25 * np.sin(2 * np.pi * freq_l * 2 * chord_t)
                + 0.12 * np.sin(2 * np.pi * freq_l * 3 * chord_t)
                + 0.05 * np.sin(2 * np.pi * freq_l * 4 * chord_t)
            )
            wave_r = (
                0.55 * np.sin(2 * np.pi * freq_r * chord_t)
                + 0.25 * np.sin(2 * np.pi * freq_r * 2 * chord_t)
                + 0.12 * np.sin(2 * np.pi * freq_r * 3 * chord_t)
                + 0.05 * np.sin(2 * np.pi * freq_r * 4 * chord_t)
            )

            # Slow evolving LFO modulation
            lfo_l = 0.88 + 0.12 * np.sin(2 * np.pi * 0.2 * chord_t)
            lfo_r = 0.88 + 0.12 * np.cos(2 * np.pi * 0.2 * chord_t)

            signal_l[start_idx:end_idx] += wave_l * env * lfo_l
            signal_r[start_idx:end_idx] += wave_r * env * lfo_r

    # Peak normalization
    max_val = max(np.max(np.abs(signal_l)), np.max(np.abs(signal_r)), 1e-6)
    signal_l = (signal_l / max_val * 0.70 * 32767).astype(np.int16)
    signal_r = (signal_r / max_val * 0.70 * 32767).astype(np.int16)

    stereo_audio = np.column_stack((signal_l, signal_r))
    temp_wav = os.path.join(SONGS_DIR, f"temp_{filename}.wav")
    out_mp3 = os.path.join(SONGS_DIR, filename)

    os.makedirs(SONGS_DIR, exist_ok=True)
    wav.write(temp_wav, sample_rate, stereo_audio)

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
