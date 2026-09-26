# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: run checks and publish the non-secret verification artifact.
'Verification command orchestration.'

from __future__ import annotations

import json
import sys

from ladder_dragon.harness_bootstrap import PROJECT_ROOT
from ladder_dragon.verification.harness_identity import _commit_sha
from ladder_dragon.verification.harness_parser import build_parser
from ladder_dragon.verification.harness_options import prepare_options
from ladder_dragon.verification.models import EXIT_CODES, HarnessContext
from ladder_dragon.verification.report import build_report, write_report
from ladder_dragon.verification.runner import HarnessRunner


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    options = prepare_options(args)
    context = HarnessContext(
        root=PROJECT_ROOT,
        python=sys.executable,
        options=options,
    )
    checks = HarnessRunner(context).run()
    report = build_report(context, checks, _commit_sha())
    write_report(options.output, report)
    print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    return EXIT_CODES[report.status]
