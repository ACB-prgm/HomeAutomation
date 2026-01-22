#!/usr/bin/env python3
import asyncio
import argparse
import logging
from functools import partial
from typing import Any, Dict, List
from wyoming.server import AsyncServer, AsyncTcpServer
from wyoming.info import Attribution, Info, TtsProgram, TtsVoice
from wyoming.version import __version__

from .tts_manager import TTSManager
from .handler import PiperEventHandler

_LOGGER = logging.getLogger(__name__)


async def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--voice",
        required=True,
        help="Default voice profile to use (e.g., glados_classic)",
    )
    parser.add_argument("--uri", default="stdio://", help="unix:// or tcp://")
    #
    parser.add_argument(
        "--zeroconf",
        nargs="?",
        const="HomeAutomation TTS",
        help="Enable discovery over zeroconf with name (default: HomeAutomation TTS)",
    )
    parser.add_argument("--samples-per-chunk", type=int, default=1024)
    parser.add_argument(
        "--no-streaming",
        action="store_true",
        help="Disable audio streaming on sentence boundaries",
    )
    parser.add_argument("--debug", action="store_true", help="Log DEBUG messages")
    parser.add_argument(
        "--log-format", default=logging.BASIC_FORMAT, help="Format for log messages"
    )
    parser.add_argument(
        "--version",
        action="version",
        version="0.0.1",
        help="Print version and exit",
    )
    args = parser.parse_args()
    
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO, format=args.log_format
    )
    _LOGGER.debug(args)

    tts_manager = TTSManager()
    # Load voice info
    voices_info = tts_manager.voices
    if not voices_info:
        raise RuntimeError("No voices found in configs/voices.json")

    default_voice_id = resolve_voice_id(args.voice, voices_info)
    if default_voice_id is None:
        raise ValueError(f"Unknown voice: {args.voice}")
    args.voice = default_voice_id

    voices: List[TtsVoice] = []
    for voice_id, voice_info in voices_info.items():
        locale = voice_info.get("locale")
        languages = [locale] if locale else [voice_id.split("_")[0]]
        voices.append(
            TtsVoice(
                name=voice_id,
                description=get_description(voice_id, voice_info),
                attribution=Attribution(name="local", url=""),
                installed=True,
                version=None,
                languages=languages,
            )
        )

    wyoming_info = Info(
        tts=[
            TtsProgram(
                name="sherpa-tts",
                description="Sherpa TTS (sherpa-onnx)",
                attribution=Attribution(
                    name="k2-fsa", url="https://github.com/k2-fsa/sherpa-onnx"
                ),
                installed=True,
                voices=sorted(voices, key=lambda v: v.name),
                version=__version__,
                supports_synthesize_streaming=(not args.no_streaming),
            )
        ],
    )

    # Start server
    server = AsyncServer.from_uri(args.uri)

    if args.zeroconf:
        if not isinstance(server, AsyncTcpServer):
            raise ValueError("Zeroconf requires tcp:// uri")

        from wyoming.zeroconf import HomeAssistantZeroconf

        tcp_server: AsyncTcpServer = server
        hass_zeroconf = HomeAssistantZeroconf(
            name=args.zeroconf, port=tcp_server.port, host=tcp_server.host
        )
        await hass_zeroconf.register_server()
        _LOGGER.debug("Zeroconf discovery enabled")

    _LOGGER.info("Ready")
    await server.run(
        partial(
            PiperEventHandler,
            wyoming_info,
            args,
            voices_info,
            tts_manager,
        )
    )


# -----------------------------------------------------------------------------


def get_description(voice_id: str, voice_info: Dict[str, Any]) -> str:
    """Get a human readable description for a voice."""
    display_name = voice_info.get("display_name", voice_id)
    extras: List[str] = []
    locale = voice_info.get("locale")
    if locale:
        extras.append(locale)
    gender = voice_info.get("gender")
    if gender:
        extras.append(gender)

    if extras:
        return f"{display_name} ({', '.join(extras)})"
    return display_name


def resolve_voice_id(voice_name: str, voices_info: Dict[str, Any]) -> str | None:
    if voice_name in voices_info:
        return voice_name

    voice_key = voice_name.casefold()
    for voice_id, voice_info in voices_info.items():
        display_name = voice_info.get("display_name")
        if display_name and display_name.casefold() == voice_key:
            return voice_id

    return None


# -----------------------------------------------------------------------------


def run():
    asyncio.run(main())


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        pass
