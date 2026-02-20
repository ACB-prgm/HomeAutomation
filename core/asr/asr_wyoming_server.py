#!/usr/bin/env python3
import argparse
import asyncio
import logging
from functools import partial
from pathlib import Path

from wyoming.info import AsrModel, AsrProgram, Attribution, Info
from wyoming.server import AsyncServer, AsyncTcpServer
from wyoming.version import __version__

from .asr import ASR, ASR_DIR
from .handler import AsrEventHandler

_LOGGER = logging.getLogger(__name__)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--uri", default="tcp://127.0.0.1:10300", help="unix:// or tcp://")
    parser.add_argument(
        "--name",
        default="nemo-parakeet-ctc-110m-en-int8",
        help="ASR model name for Wyoming metadata",
    )
    parser.add_argument("--language", default="en", help="Language code for transcript metadata")
    parser.add_argument("--model-path", default=str(ASR_DIR / "model.int8.onnx"))
    parser.add_argument("--tokens-path", default=str(ASR_DIR / "tokens.txt"))
    parser.add_argument("--num-threads", type=int, default=4)
    parser.add_argument("--provider", default="cpu")
    parser.add_argument(
        "--zeroconf",
        nargs="?",
        const="HomeAutomation ASR",
        help="Enable discovery over zeroconf with name (default: HomeAutomation ASR)",
    )
    parser.add_argument("--debug", action="store_true", help="Log DEBUG messages")
    parser.add_argument("--log-format", default=logging.BASIC_FORMAT, help="Format for log messages")
    parser.add_argument(
        "--version",
        action="version",
        version="0.0.1",
        help="Print version and exit",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO, format=args.log_format)
    _LOGGER.debug(args)

    model_path = Path(args.model_path)
    tokens_path = Path(args.tokens_path)
    if not model_path.exists():
        raise FileNotFoundError(f"ASR model file not found: {model_path}")
    if not tokens_path.exists():
        raise FileNotFoundError(f"ASR tokens file not found: {tokens_path}")

    asr = ASR(
        r_model_path=model_path,
        r_tokens_path=tokens_path,
        num_threads=args.num_threads,
        provider=args.provider,
    )

    asr_model = AsrModel(
        name=args.name,
        description=f"Sherpa NeMo CTC ({args.language})",
        attribution=Attribution(name="k2-fsa", url="https://github.com/k2-fsa/sherpa-onnx"),
        installed=True,
        version=None,
        languages=[args.language],
    )

    wyoming_info = Info(
        asr=[
            AsrProgram(
                name="sherpa-asr",
                description="Sherpa ASR (sherpa-onnx)",
                attribution=Attribution(name="k2-fsa", url="https://github.com/k2-fsa/sherpa-onnx"),
                installed=True,
                version=__version__,
                models=[asr_model],
                supports_transcript_streaming=False,
            )
        ]
    )

    server = AsyncServer.from_uri(args.uri)

    if args.zeroconf:
        if not isinstance(server, AsyncTcpServer):
            raise ValueError("Zeroconf requires tcp:// uri")

        from wyoming.zeroconf import HomeAssistantZeroconf

        tcp_server: AsyncTcpServer = server
        hass_zeroconf = HomeAssistantZeroconf(
            name=args.zeroconf,
            port=tcp_server.port,
            host=tcp_server.host,
        )
        await hass_zeroconf.register_server()
        _LOGGER.debug("Zeroconf discovery enabled")

    _LOGGER.info("Ready")
    await server.run(partial(AsrEventHandler, wyoming_info, asr, args.language))


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        pass
