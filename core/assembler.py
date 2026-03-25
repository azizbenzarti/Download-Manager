# Merge Segments into a single file
from __future__ import annotations

import os
from typing import Iterable

from core.models import SegmentInfo


class FileAssembler:
    """
    Responsible for merging downloaded segment files into the final output file.
    """

    def assemble(self, segments: Iterable[SegmentInfo], output_file: str) -> None:
        sorted_segments = sorted(segments, key=lambda s: s.segment_id)

        output_dir = os.path.dirname(output_file)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        with open(output_file, "wb") as final_file:
            for segment in sorted_segments:
                if not os.path.exists(segment.temp_file_path):
                    raise FileNotFoundError(
                        f"Missing segment file: {segment.temp_file_path}"
                    )

                with open(segment.temp_file_path, "rb") as part_file:
                    while True:
                        chunk = part_file.read(8192)
                        if not chunk:
                            break
                        final_file.write(chunk)

    def cleanup_segments(self, segments: Iterable[SegmentInfo]) -> None:
        for segment in segments:
            try:
                if os.path.exists(segment.temp_file_path):
                    os.remove(segment.temp_file_path)
            except OSError:
                pass