"""Security, metadata, and privacy checks using entirely synthetic fixtures."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock
import zipfile

from scripts import inventory


class TemporaryFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="inventory-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.data = self.root / "private-data"

    def archive(self, members):
        path = self.root / "fixture.zip"
        with zipfile.ZipFile(path, "w") as output:
            for name, payload in members:
                output.writestr(name, payload)
        return path

    def parse(self, payload):
        path = self.root / "fixture.vtt"
        path.write_text(payload, encoding="utf-8")
        return inventory.parse_vtt(path)


class ArchiveSafetyTests(TemporaryFixture):
    def test_rejects_unsafe_windows_and_zip_paths(self):
        unsafe = [
            "", "../outside.mp4", "nested/../../outside.mp4", "/absolute.mp4",
            "C:/absolute.mp4", "C:relative.mp4", "\\\\server\\share\\clip.mp4",
            "folder\\clip.mp4", "folder/./clip.mp4", "folder//clip.mp4",
            "clip.mp4:stream", "folder./clip.mp4", "folder /clip.mp4",
            "CON.mp4", "aux.vtt", "nested/NUL.pdf", "COM1.mp4", "LPT9.vtt",
            "COM\u00b9.mp4", "LPT\u00b2.vtt", "CONIN$.mp4", "CONOUT$.pdf",
            "clip?.mp4", "clip*.mp4", "clip|.mp4", "clip\x00.mp4",
        ]
        for name in unsafe:
            with self.subTest(name=name), self.assertRaises(inventory.InventoryError):
                inventory.safe_member_path(name, self.data)

    def test_accepts_valid_nested_name(self):
        expected = self.data / "folder" / "lesson 01.mp4"
        self.assertEqual(inventory.safe_member_path("folder/lesson 01.mp4", self.data), expected)

    def test_rejects_escape_in_guard(self):
        with self.assertRaises(inventory.InventoryError):
            inventory.guard_path(self.data, self.root / "outside.mp4")

    def test_rejects_zip_symbolic_link(self):
        info = zipfile.ZipInfo("link.mp4")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive = self.archive([(info, "../outside.mp4")])
        with zipfile.ZipFile(archive) as source, self.assertRaises(inventory.InventoryError):
            inventory.extract_archive(source, self.data)
        self.assertFalse(self.data.exists())

    def test_rejects_zip_special_file(self):
        info = zipfile.ZipInfo("pipe.mp4")
        info.create_system = 3
        info.external_attr = (stat.S_IFIFO | 0o600) << 16
        archive = self.archive([(info, b"")])
        with zipfile.ZipFile(archive) as source, self.assertRaises(inventory.InventoryError):
            inventory.inspect_archive(source, self.data)

    def test_preflight_rejects_traversal_before_any_extraction(self):
        archive = self.archive([("valid.mp4", b"video"), ("../outside.vtt", b"WEBVTT")])
        with zipfile.ZipFile(archive) as source, self.assertRaises(inventory.InventoryError):
            inventory.extract_archive(source, self.data)
        self.assertFalse(self.data.exists())
        self.assertFalse((self.root / "outside.vtt").exists())

    def test_preflight_rejects_case_collisions(self):
        archive = self.archive([("folder/Lesson.mp4", b"one"), ("folder/lesson.MP4", b"two")])
        with zipfile.ZipFile(archive) as source, self.assertRaisesRegex(
            inventory.InventoryError, "duplicate_or_case_colliding"
        ):
            inventory.extract_archive(source, self.data)
        self.assertFalse(self.data.exists())

    def test_preflight_rejects_unicode_normalization_collisions(self):
        archive = self.archive([("caf\u00e9.mp4", b"one"), ("cafe\u0301.mp4", b"two")])
        with zipfile.ZipFile(archive) as source, self.assertRaisesRegex(
            inventory.InventoryError, "duplicate_or_case_colliding"
        ):
            inventory.inspect_archive(source, self.data)

    def test_trailing_ascii_spaces_are_extracted_only_under_anonymous_names(self):
        original_name = "folder /lesson.mp4 "
        archive = self.archive([(original_name, b"synthetic-video")])
        with zipfile.ZipFile(archive) as source:
            entries = inventory.extract_archive(source, self.data)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["original_name"], original_name)
        self.assertEqual(entries[0]["extension"], ".mp4")
        destination = self.data / "inventory" / "extracted" / "A0001.mp4"
        self.assertEqual(entries[0]["local_path"], destination)
        self.assertEqual(destination.read_bytes(), b"synthetic-video")
        self.assertFalse((self.data / "folder").exists())
        self.assertEqual(list(destination.parent.iterdir()), [destination])

    def test_trailing_space_canonical_collision_is_rejected(self):
        for names in (
            ("folder /lesson.mp4", "folder/lesson.mp4"),
            ("folder/lesson.mp4 ", "folder/lesson.mp4"),
        ):
            with self.subTest(names=names):
                archive = self.archive([(names[0], b"one"), (names[1], b"two")])
                with zipfile.ZipFile(archive) as source, self.assertRaisesRegex(
                    inventory.InventoryError, "duplicate_or_case_colliding"
                ):
                    inventory.extract_archive(source, self.data)
                self.assertFalse(self.data.exists())

    def test_space_only_and_traversal_with_spaces_are_rejected(self):
        for name in (" /lesson.mp4", "folder/ /lesson.mp4", ".. /outside.mp4", "folder/.. /outside.mp4"):
            with self.subTest(name=name):
                archive = self.archive([(name, b"synthetic-video")])
                with zipfile.ZipFile(archive) as source, self.assertRaises(inventory.InventoryError):
                    inventory.extract_archive(source, self.data)
                self.assertFalse(self.data.exists())

    def test_rejects_mocked_destination_symlink_and_junction(self):
        for method in ("is_symlink", "is_junction"):
            with self.subTest(method=method), mock.patch.object(Path, method, return_value=True):
                with self.assertRaisesRegex(inventory.InventoryError, "symlink_or_junction"):
                    inventory.guard_path(self.data, self.data / "inventory" / "extracted")

    def test_rejects_real_destination_symlink_when_platform_allows(self):
        self.data.mkdir()
        outside = self.root / "outside"
        outside.mkdir()
        link = self.data / "inventory"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("Creating a symlink is unavailable for this Windows account.")
        archive = self.archive([("lesson.mp4", b"video")])
        with zipfile.ZipFile(archive) as source, self.assertRaises(inventory.InventoryError):
            inventory.extract_archive(source, self.data)
        self.assertEqual(list(outside.iterdir()), [])

    def test_reuses_verified_existing_file_and_preserves_archive(self):
        archive = self.archive([("lesson.mp4", b"synthetic-video")])
        before = archive.read_bytes()
        with zipfile.ZipFile(archive) as source:
            first = inventory.extract_archive(source, self.data)
        destination = first[0]["local_path"]
        timestamp = destination.stat().st_mtime_ns
        with zipfile.ZipFile(archive) as source:
            second = inventory.extract_archive(source, self.data)
        self.assertEqual(destination.name, "A0001.mp4")
        self.assertEqual(destination.read_bytes(), b"synthetic-video")
        self.assertEqual(destination.stat().st_mtime_ns, timestamp)
        self.assertEqual(second[0]["extraction_status"], "reused_crc_verified")
        self.assertEqual(archive.read_bytes(), before)

    def test_same_size_existing_conflict_is_never_overwritten(self):
        archive = self.archive([("lesson.mp4", b"new")])
        destination = self.data / "inventory" / "extracted" / "A0001.mp4"
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b"old")
        with zipfile.ZipFile(archive) as source, self.assertRaisesRegex(
            inventory.InventoryError, "existing_file_conflict_no_overwrite"
        ):
            inventory.extract_archive(source, self.data)
        self.assertEqual(destination.read_bytes(), b"old")

    def test_low_disk_space_stops_before_creating_data(self):
        archive = self.archive([("lesson.mp4", b"video")])
        with mock.patch.object(inventory.shutil, "disk_usage", return_value=mock.Mock(free=0)):
            with zipfile.ZipFile(archive) as source, self.assertRaisesRegex(
                inventory.InventoryError, "insufficient_disk_space"
            ):
                inventory.extract_archive(source, self.data)
        self.assertFalse(self.data.exists())


class CaptionMetadataTests(TemporaryFixture):
    def test_cue_ids_settings_multiline_tags_and_entities(self):
        result = self.parse(
            "\ufeffWEBVTT\n\n"
            "NOTE synthetic metadata\n00:00.000 --> 99:00.000\nignored\n\n"
            "STYLE\n::cue { color: white; }\n\n"
            "REGION\nid:one\n\n"
            "cue-one\n00:00:01.000 --> 00:00:03.500 align:start position:0%\n"
            "<v SyntheticSpeaker>Hello &amp; welcome.</v>\n<b>Two lines.</b>\n\n"
            "cue-two\n00:04.000 --> 00:05.000\n&#72;i &nbsp;there\n"
        )
        self.assertTrue(result["webvtt_header_present"])
        self.assertEqual(result["cue_count"], 2)
        self.assertEqual(result["timing_line_count"], 2)
        self.assertEqual(result["invalid_timing_count"], 0)
        self.assertEqual(result["max_cue_end_seconds"], 5.0)
        self.assertEqual(result["word_count"], 6)
        self.assertEqual(result["alphabetic_character_count"], 27)
        self.assertTrue(result["potentially_usable_text"])
        self.assertNotIn("SyntheticSpeaker", json.dumps(result))
        self.assertNotIn("Hello", json.dumps(result))

    def test_empty_tags_entities_and_numbers_do_not_establish_lexical_text(self):
        result = self.parse(
            "WEBVTT\n\n00:00.000 --> 00:01.000\n<v SyntheticSpeaker></v>&nbsp;\n\n"
            "00:01.000 --> 00:02.000\n12345\n"
        )
        self.assertEqual(result["cue_count"], 2)
        self.assertEqual(result["text_cue_count"], 1)
        self.assertEqual(result["alphabetic_character_count"], 0)
        self.assertFalse(result["potentially_usable_text"])

    def test_non_speech_labels_do_not_establish_lexical_text(self):
        result = self.parse(
            "WEBVTT\n\n00:00.000 --> 00:01.000\n[music]\n\n"
            "00:01.000 --> 00:02.000\n(applause)\n"
        )
        self.assertEqual(result["non_speech_only_cue_count"], 2)
        self.assertEqual(result["lexical_cue_count"], 0)
        self.assertFalse(result["potentially_usable_text"])

    def test_invalid_times_are_counted_but_not_used_for_endpoint(self):
        result = self.parse(
            "WEBVTT\n\n00:00.000 --> 00:02.000\nvalid\n\n"
            "00:61.000 --> 01:02.000\ninvalid seconds\n\n"
            "00:60:00.000 --> 01:00:01.000\ninvalid minutes\n\n"
            "00:03.000 --> 00:03.000\nzero length\n\n"
            "00:05.000 --> 00:04.000\nreversed\n\n"
            "00:00 --> 00:09.000\nmissing fraction\n\n"
            "00:01.000-->00:10.000\nmissing delimiter spacing\n"
        )
        self.assertEqual(result["timing_line_count"], 7)
        self.assertEqual(result["invalid_timing_count"], 6)
        self.assertEqual(result["cue_count"], 1)
        self.assertEqual(result["max_cue_end_seconds"], 2.0)
        self.assertEqual(result["word_count"], 1)

    def test_reports_non_monotonic_starts_and_maximum_not_last_end(self):
        result = self.parse(
            "WEBVTT\n\n00:10.000 --> 00:20.000\nfirst\n\n"
            "00:01.000 --> 00:02.000\nsecond\n"
        )
        self.assertEqual(result["non_monotonic_start_count"], 1)
        self.assertEqual(result["max_cue_end_seconds"], 20.0)

    def test_empty_and_malformed_documents(self):
        for payload in ("", "WEBVTT\n", "not a caption file\nno timing lines"):
            with self.subTest(payload=payload):
                result = self.parse(payload)
                self.assertEqual(result["cue_count"], 0)
                self.assertIsNone(result["max_cue_end_seconds"])
                self.assertFalse(result["potentially_usable_text"])

    def test_size_limit_is_checked_before_reading(self):
        path = self.root / "large.vtt"
        path.write_bytes(b"WEBVTT")
        with mock.patch.object(inventory, "MAX_VTT_BYTES", 1):
            with self.assertRaisesRegex(inventory.InventoryError, "vtt_size_limit"):
                inventory.parse_vtt(path)


class PairingTests(unittest.TestCase):
    def entries(self, *names):
        return [
            {"original_name": name, "extension": Path(name).suffix.lower(),
             "size_bytes": 1, "asset_id": f"A{index:04d}"}
            for index, name in enumerate(names, 1)
        ]

    def test_unique_exact_and_suffix_candidates_remain_possible(self):
        videos, captions = inventory.pair_entries(self.entries(
            "First.mp4", "first.vtt", "Second.mp4", "Second_transcript.vtt"
        ))
        self.assertEqual([v["match_status"] for v in videos], ["possible_unique"] * 2)
        self.assertEqual([v["match_basis"] for v in videos], ["exact_stem", "caption_suffix"])
        self.assertEqual([c["match_status"] for c in captions], ["possible_unique"] * 2)

    def test_multiple_caption_candidates_are_not_guessed(self):
        videos, captions = inventory.pair_entries(self.entries(
            "lesson.mp4", "lesson.vtt", "lesson_captions.vtt"
        ))
        self.assertEqual(videos[0]["match_status"], "ambiguous")
        self.assertIsNone(videos[0]["paired_transcript_id"])
        self.assertEqual(len(videos[0]["candidate_transcript_ids"]), 2)
        self.assertTrue(all(c["match_status"] == "ambiguous" for c in captions))

    def test_duplicate_video_stems_across_folders_are_not_guessed(self):
        videos, captions = inventory.pair_entries(self.entries(
            "one/lesson.mp4", "two/lesson.mp4", "one/lesson.vtt"
        ))
        self.assertTrue(all(v["match_status"] == "ambiguous" for v in videos))
        self.assertTrue(all(v["paired_transcript_id"] is None for v in videos))
        self.assertEqual(captions[0]["match_status"], "ambiguous")

    def test_unrelated_names_are_unmatched(self):
        videos, captions = inventory.pair_entries(self.entries("one.mp4", "two.vtt"))
        self.assertEqual(videos[0]["match_status"], "unmatched")
        self.assertEqual(videos[0]["candidate_transcript_ids"], [])
        self.assertEqual(captions[0]["match_status"], "unmatched")


class PrivacyAndDurationTests(TemporaryFixture):
    def test_synthetic_run_keeps_names_and_payload_out_of_public_output(self):
        private_stem = "synthetic-private-recording-marker"
        private_payload = "SyntheticSecretCaptionMarker"
        archive = self.archive([
            (private_stem + ".mp4", b"synthetic-video"),
            (private_stem + ".vtt", f"WEBVTT\n\n00:00.000 --> 00:02.000\n{private_payload}\n"),
            ("synthetic-private-brief-marker.pdf", b"%PDF synthetic fixture"),
        ])
        before = archive.read_bytes()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            summary = inventory.run_inventory(archive, self.data, ffprobe=None)
        public = output.getvalue() + json.dumps(summary)
        for marker in (private_stem, private_payload, "synthetic-private-brief-marker"):
            self.assertNotIn(marker, public)
        video = summary["videos"][0]
        self.assertEqual(video["transcript_end_seconds"], 2.0)
        self.assertIsNone(video["media"]["video_duration_seconds"])
        self.assertIsNone(video["media"]["has_audio"])
        self.assertIsNone(video["transcript_end_minus_media_duration_seconds"])
        self.assertEqual(archive.read_bytes(), before)
        mappings = list((self.data / "inventory" / "reports").glob("*/filename-mapping.private.json"))
        self.assertEqual(len(mappings), 1)
        self.assertIn(private_stem, mappings[0].read_text(encoding="utf-8"))
        self.assertNotIn(private_payload, mappings[0].read_text(encoding="utf-8"))

    def test_ffprobe_duration_and_audio_are_distinct_from_caption_metadata(self):
        probe = {"format": {"duration": "30.25"}, "streams": [
            {"codec_type": "video", "duration": "30.0"}, {"codec_type": "audio"}
        ]}
        completed = mock.Mock(stdout=json.dumps(probe))
        with mock.patch.object(inventory.subprocess, "run", return_value=completed) as call:
            result = inventory.probe_video(self.root / "A0001.mp4", "ffprobe")
        self.assertEqual(result["video_duration_seconds"], 30.25)
        self.assertEqual(result["video_stream_duration_seconds"], 30.0)
        self.assertEqual(result["duration_source"], "container")
        self.assertTrue(result["has_audio"])
        self.assertEqual(result["audio_stream_count"], 1)
        self.assertNotIn("shell", call.call_args.kwargs)

    def test_invalid_probe_duration_is_not_reported_as_numeric(self):
        completed = mock.Mock(stdout=json.dumps({"format": {"duration": "NaN"}, "streams": []}))
        with mock.patch.object(inventory.subprocess, "run", return_value=completed):
            result = inventory.probe_video(self.root / "A0001.mp4", "ffprobe")
        self.assertIsNone(result["video_duration_seconds"])
        self.assertFalse(result["has_audio"])


if __name__ == "__main__":
    unittest.main()
