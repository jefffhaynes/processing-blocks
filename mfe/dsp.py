import argparse
import json
import numpy as np
import os, sys
from matplotlib import cm
import io, base64
import matplotlib.pyplot as plt
import time
import matplotlib
from scipy import signal as sn
import scipy.io.wavfile as wav

# Load our SpeechPy fork
MODULE_PATH = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'third_party', 'speechpy', '__init__.py')
MODULE_NAME = 'speechpy'
import importlib
import sys
spec = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
speechpy = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = speechpy
spec.loader.exec_module(speechpy)

# matplotlib.use('Svg')

def generate_features(implementation_version, draw_graphs, raw_data, axes, sampling_freq,
                      frame_length, frame_stride, num_filters, fft_length,
                      low_frequency, high_frequency, win_size, noise_floor_db):
    if (implementation_version != 1 and implementation_version != 2 and implementation_version != 3):
        raise Exception('implementation_version should be 1, 2 or 3')

    if (num_filters < 2):
        raise Exception('Filter number should be at least 2')

    fs = sampling_freq
    low_frequency = None if low_frequency == 0 else low_frequency
    high_frequency = None if high_frequency == 0 else high_frequency

    # reshape first
    raw_data = raw_data.reshape(int(len(raw_data) / len(axes)), len(axes))

    features = []
    graphs = []

    width = 0
    height = 0

    for ax in range(0, len(axes)):
        signal = raw_data[:,ax]

        if implementation_version >= 3:
            # Rescale to [-1, 1] and add preemphasis
            signal = (signal / 2**15).astype(np.float32)
            signal = speechpy.processing.preemphasis(signal, cof=0.98, shift=1)

        ############# Extract MFCC features #############
        mfe, energy = speechpy.feature.mfe(signal, sampling_frequency=fs, implementation_version=implementation_version,
                                           frame_length=frame_length,
                                           frame_stride=frame_stride, num_filters=num_filters, fft_length=fft_length,
                                           low_frequency=low_frequency, high_frequency=high_frequency)

        if implementation_version < 3:
            mfe_cmvn = speechpy.processing.cmvnw(mfe, win_size=win_size, variance_normalization=False)

            if (np.min(mfe_cmvn) != 0 and np.max(mfe_cmvn) != 0):
                mfe_cmvn = (mfe_cmvn - np.min(mfe_cmvn)) / (np.max(mfe_cmvn) - np.min(mfe_cmvn))

            mfe_cmvn[np.isnan(mfe_cmvn)] = 0

            flattened = mfe_cmvn.flatten()
        else:
            # Clip to avoid zero values
            mfe = np.clip(mfe, 1e-30, None)
            # Convert to dB scale
            # log_mel_spec = 10 * log10(mel_spectrograms)
            mfe = 10 * np.log10(mfe)

            # Add power offset and clip values below 0 (hard filter)
            # log_mel_spec = (log_mel_spec + self._power_offset - 32 + 32.0) / 64.0
            # log_mel_spec = tf.clip_by_value(log_mel_spec, 0, 1)
            mfe = (mfe - noise_floor_db) / ((-1 * noise_floor_db) + 12)
            mfe = np.clip(mfe, 0, 1)

            # Quantize to 8 bits and dequantize back to float32
            mfe = np.uint8(np.around(mfe * 2**8))
            # clip to 2**8
            mfe = np.clip(mfe, 0, 255)
            mfe = np.float32(mfe / 2**8)

            mfe_cmvn = mfe

            flattened = mfe.flatten()

        features = np.concatenate((features, flattened))

        width = np.shape(mfe)[0]
        height = np.shape(mfe)[1]

        if draw_graphs:
            # make visualization too
            fig, ax = plt.subplots()
            fig.set_size_inches(18.5, 20.5)
            ax.set_axis_off()
            mfe_data = np.swapaxes(mfe_cmvn, 0, 1)
            cax = ax.imshow(mfe_data, interpolation='nearest', cmap=cm.coolwarm, origin='lower')

            buf = io.BytesIO()

            # plt.savefig(buf, format='svg', bbox_inches='tight', pad_inches=0)
            plt.savefig(buf, bbox_inches='tight', pad_inches=0)

            buf.seek(0)
            image = (base64.b64encode(buf.getvalue()).decode('ascii'))

            buf.close()

            graphs.append({
                'name': 'Spectrogram',
                'image': image,
                'imageMimeType': 'image/svg+xml',
                'type': 'image'
            })

            # plt.savefig("myimg.svg")
            plt.show()

        return features

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='MFCC script for audio data')
    # parser.add_argument('--features', type=str, required=True,
    #                     help='Axis data as a flattened WAV file (pass as comma separated values)')
    parser.add_argument('--in_dir', type=str, required=True, 
                        help='Input directory')
    parser.add_argument('--features', type=str, required=True, 
                        help='Features output file')
    parser.add_argument('--labels', type=str, required=True, 
                        help='Labels output file')
    parser.add_argument('--draw-graphs', type=lambda x: (str(x).lower() in ['true','1', 'yes']), default=False,
                        help='Whether to draw graphs')
    parser.add_argument('--frame_length', type=float, default=0.02,
                        help='The length of each frame in seconds')
    parser.add_argument('--frame_stride', type=float, default=0.02,
                        help='The step between successive frames in seconds')
    parser.add_argument('--num_filters', type=int, default=40,
                        help='The number of filters in the filterbank')
    parser.add_argument('--fft_length', type=int, default=256,
                        help='Number of FFT points')
    parser.add_argument('--win_size', type=int, default=101,
                        help='The size of sliding window for local normalization')
    parser.add_argument('--noise-floor-db', type=int, default=-52,
                        help='Everything below this loudness will be dropped')
    parser.add_argument('--low_frequency', type=int, default=0,
                        help='Lowest band edge of mel filters')
    parser.add_argument('--high_frequency', type=int, default=0,
                        help='Highest band edge of mel filters. If set to 0 this is equal to samplerate / 2.')

    args = parser.parse_args()

    raw_axes = ['axes']

    all_features = []
    labels = []

    try:
        for filename in os.listdir(args.in_dir):

            print(filename)

            file = os.path.join(args.in_dir, filename)

            frequency, raw_features = wav.read(file)

            label, _ = filename.split(".", 1)

            if label == "noise":
                label_value = 0
            elif label == "brighter":
                label_value = 1
            elif label == "dimmer":
                label_value = 2
            else: continue

            features = generate_features(3, args.draw_graphs, raw_features, raw_axes, frequency,
                args.frame_length, args.frame_stride, args.num_filters, args.fft_length,
                args.low_frequency, args.high_frequency, args.win_size, args.noise_floor_db)

            if features.shape == (2000,):
                all_features.append([features])
                labels.append([label_value])

    except Exception as e:
        print(e, file=sys.stderr)
        exit(1) 
    
    np.save(args.features, all_features)
    np.save(args.labels, labels)