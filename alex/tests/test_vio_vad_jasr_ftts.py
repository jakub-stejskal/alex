#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import unicode_literals
if __name__ == '__main__':
    import autopath

import argparse
import multiprocessing
import sys
import time

from alex.components.hub.vio import VoipIO
from alex.components.hub.vad import VAD
from alex.components.hub.asr import ASR
from alex.components.hub.tts import TTS
from alex.components.hub.messages import Command, ASRHyp, TTSText
from alex.utils.config import Config

#########################################################################
#########################################################################
if __name__ == '__main__':

    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""
        test_vio_vad_jasr_ftts.py tests the VoipIO, VAD, ASR, and TTS components.

        This application uses the Julis ASR and Flite TTS.

        The program reads the default config in the resources directory ('../resources/default.cfg') and any
        additional config files passed as an argument of a '-c'. The additional config file
        overwrites any default or previous values.

      """)

    parser.add_argument('-c', "--configs", nargs='+',
                        help='additional configuration files')
    args = parser.parse_args()

    cfg = Config.load_configs(args.configs)

    # set using Google ASR and Google TTS
    cfg['ASR']['type'] = 'Julius'
    cfg['TTS']['type'] = 'Flite'

    #########################################################################
    #########################################################################
    cfg['Logging']['system_logger'].info("Test of the VoipIO, VAD, ASR, and TTS components\n" + "=" * 120)

    vio_commands, vio_child_commands = multiprocessing.Pipe()
    # used to send commands to VoipIO

    vio_record, vio_child_record = multiprocessing.Pipe()
    # I read from this connection recorded audio

    vio_play, vio_child_play = multiprocessing.Pipe()
    # I write in audio to be played


    vad_commands, vad_child_commands = multiprocessing.Pipe()
    # used to send commands to VAD

    vad_audio_out, vad_child_audio_out = multiprocessing.Pipe()
    # used to read output audio from VAD


    asr_commands, asr_child_commands = multiprocessing.Pipe()
    # used to send commands to ASR

    asr_hypotheses_out, asr_child_hypotheses = multiprocessing.Pipe()
    # used to read ASR hypotheses


    tts_commands, tts_child_commands = multiprocessing.Pipe()
    # used to send commands to TTS

    tts_text_in, tts_child_text_in = multiprocessing.Pipe()
    # used to send TTS text


    command_connections = (vio_commands, vad_commands, asr_commands, tts_commands)

    non_command_connections = (vio_record, vio_child_record,
                               vio_play, vio_child_play,
                               vad_audio_out, vad_child_audio_out,
                               asr_hypotheses_out, asr_child_hypotheses,
                               tts_text_in, tts_child_text_in)

    close_event = multiprocessing.Event()

    vio = VoipIO(cfg, vio_child_commands, vio_child_record, vio_child_play, close_event)
    vad = VAD(cfg, vad_child_commands, vio_record, vad_child_audio_out, close_event)
    asr = ASR(cfg, asr_child_commands, vad_audio_out, asr_child_hypotheses, close_event)
    tts = TTS(cfg, tts_child_commands, tts_child_text_in, vio_play, close_event)

    vio.start()
    vad.start()
    asr.start()
    tts.start()

    # Actively call a number configured.
    #vio_commands.send(Command('make_call(destination="\'Bejcek Eduard\' <sip:4366@SECRET:5066>")', 'HUB', 'VoipIO'))
    #vio_commands.send(Command('make_call(destination="sip:4366@SECRET:5066")', 'HUB', 'VoipIO'))
    #vio_commands.send(Command('make_call(destination="4366")', 'HUB', 'VoipIO'))
    #vio_commands.send(Command('make_call(destination="155")', 'HUB', 'VoipIO'))

    count = 0
    max_count = 50000
    while count < max_count:
        time.sleep(cfg['Hub']['main_loop_sleep_time'])
        count += 1

        if asr_hypotheses_out.poll():
            asr_hyp = asr_hypotheses_out.recv()

            if isinstance(asr_hyp, ASRHyp):
                m = []
                m.append("Recognised hypotheses:")
                m.append("-" * 120)
                m.append(unicode(asr_hyp.hyp))
                cfg['Logging']['system_logger'].info('\n'.join(m))

                # get top hypotheses text
                top_text = asr_hyp.hyp.get_best_utterance()

                if top_text:
                    tts_text_in.send(TTSText('Recognized text: %s' % top_text))
                else:
                    tts_text_in.send(TTSText('Nothing was recognised'))

        # read all messages
        if vio_commands.poll():
            command = vio_commands.recv()

            if isinstance(command, Command):
                if command.parsed['__name__'] == "incoming_call" or command.parsed['__name__'] == "make_call":
                    cfg['Logging']['system_logger'].session_start(command.parsed['remote_uri'])
                    cfg['Logging']['system_logger'].session_system_log('config = ' + unicode(cfg))
                    cfg['Logging']['system_logger'].info(command)

                    cfg['Logging']['session_logger'].session_start(cfg['Logging']['system_logger'].get_session_dir_name())
                    cfg['Logging']['session_logger'].config('config = ' + unicode(cfg))
                    cfg['Logging']['session_logger'].header(cfg['Logging']["system_name"], cfg['Logging']["version"])
                    cfg['Logging']['session_logger'].input_source("voip")

                    tts_text_in.send(TTSText('Say something and the recognized text will be played back.'))

                elif command.parsed['__name__'] == "call_disconnected":
                    cfg['Logging']['system_logger'].info(command)

                    vio_commands.send(Command('flush()', 'HUB', 'VoipIO'))

                    cfg['Logging']['system_logger'].session_end()
                    cfg['Logging']['session_logger'].session_end()

        # read all messages
        for c in command_connections:
            if c.poll():
                command = c.recv()
                cfg['Logging']['system_logger'].info(command)

    # stop processes
    vio_commands.send(Command('stop()', 'HUB', 'VoipIO'))
    vad_commands.send(Command('stop()', 'HUB', 'VAD'))
    asr_commands.send(Command('stop()', 'HUB', 'ASR'))
    tts_commands.send(Command('stop()', 'HUB', 'TTS'))

    # clean connections
    for c in command_connections:
        while c.poll():
            c.recv()

    for c in non_command_connections:
        while c.poll():
            c.recv()

    # wait for processes to stop
    vio.join()
    cfg['Logging']['system_logger'].debug('VIO stopped.')
    vad.join()
    cfg['Logging']['system_logger'].debug('VAD stopped.')
    asr.join()
    cfg['Logging']['system_logger'].debug('ASR stopped.')
    tts.join()
    cfg['Logging']['system_logger'].debug('TTS stopped.')
