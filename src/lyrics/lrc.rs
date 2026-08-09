// SPDX-FileCopyrightText: 2026
// SPDX-License-Identifier: GPL-3.0-or-later

use once_cell::sync::Lazy;
use regex::Regex;

static TIMESTAMP_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]").unwrap());
static METADATA_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"^\[([a-zA-Z_]+):([^\]]*)\]").unwrap());
static WORD_TAG_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"<\d{1,3}:\d{1,2}(?:[.:]\d{1,3})?>").unwrap());

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LyricLine {
    pub time_ms: u64,
    pub text: String,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Lyrics {
    pub lines: Vec<LyricLine>,
    pub offset_ms: i64,
    /// False when the lines carry no timestamps. Unsynced lyrics are shown
    /// statically: nothing to highlight, nothing to scroll to.
    pub synced: bool,
}

impl Lyrics {
    /// Parses LRC text. Never fails: unrecognised lines are skipped, so any
    /// input yields a `Lyrics` (possibly with no lines).
    pub fn parse(input: &str) -> Self {
        let input = input.strip_prefix('\u{feff}').unwrap_or(input);
        let mut lines: Vec<LyricLine> = Vec::new();
        let mut offset_ms: i64 = 0;

        for raw in input.lines() {
            let mut rest = raw.trim_end_matches('\r').trim_start();
            let mut stamps: Vec<u64> = Vec::new();

            loop {
                if let Some(caps) = TIMESTAMP_RE.captures(rest) {
                    let minutes: u64 = caps[1].parse().unwrap_or(0);
                    let seconds: u64 = caps[2].parse().unwrap_or(0);
                    let fraction = caps
                        .get(3)
                        .map(|m| {
                            let digits = m.as_str();
                            let value: u64 = digits.parse().unwrap_or(0);
                            match digits.len() {
                                1 => value * 100,
                                2 => value * 10,
                                _ => value,
                            }
                        })
                        .unwrap_or(0);
                    stamps.push(minutes * 60_000 + seconds * 1_000 + fraction);
                    let end = caps.get(0).unwrap().end();
                    rest = &rest[end..];
                    continue;
                }

                // Metadata may only precede the first timestamp on a line.
                if stamps.is_empty() {
                    if let Some(caps) = METADATA_RE.captures(rest) {
                        if caps[1].eq_ignore_ascii_case("offset") {
                            if let Ok(value) = caps[2].trim().parse::<i64>() {
                                offset_ms = value;
                            }
                        }
                        let end = caps.get(0).unwrap().end();
                        rest = &rest[end..];
                        continue;
                    }
                }

                break;
            }

            if stamps.is_empty() {
                continue;
            }

            let text = WORD_TAG_RE.replace_all(rest, "").trim().to_string();
            for time_ms in stamps {
                lines.push(LyricLine {
                    time_ms,
                    text: text.clone(),
                });
            }
        }

        lines.sort_by_key(|line| line.time_ms);

        Lyrics {
            lines,
            offset_ms,
            synced: true,
        }
    }

    /// Parses lyrics that carry no timestamps, one line of text per line.
    ///
    /// Used as a fallback when a file has real words but no timing, which is
    /// otherwise indistinguishable from an empty file.
    pub fn parse_unsynced(input: &str) -> Self {
        let input = input.strip_prefix('\u{feff}').unwrap_or(input);

        let lines = input
            .lines()
            .map(|raw| raw.trim_end_matches('\r').trim())
            .filter(|text| !text.is_empty())
            // Drop metadata tags; they are not words anybody wants to read.
            .filter(|text| METADATA_RE.captures(text).is_none())
            .map(|text| LyricLine {
                time_ms: 0,
                text: text.to_string(),
            })
            .collect();

        Lyrics {
            lines,
            offset_ms: 0,
            synced: false,
        }
    }

    /// True when there is nothing worth showing: no lines at all, or every
    /// line is an instrumental gap.
    pub fn is_empty(&self) -> bool {
        self.lines.iter().all(|line| line.text.is_empty())
    }

    /// Index of the last line whose adjusted timestamp has been reached.
    /// `None` before the first line.
    ///
    /// A positive `[offset:]` makes lyrics appear earlier.
    pub fn active_line_at(&self, position_ms: u64) -> Option<usize> {
        // Without timestamps there is nothing to follow.
        if !self.synced || self.lines.is_empty() {
            return None;
        }

        let position = position_ms as i64;
        let index = self
            .lines
            .partition_point(|line| line.time_ms as i64 - self.offset_ms <= position);

        if index == 0 {
            None
        } else {
            Some(index - 1)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_centisecond_timestamps() {
        let l = Lyrics::parse("[00:12.34]first placeholder line");
        assert_eq!(l.lines.len(), 1);
        assert_eq!(l.lines[0].time_ms, 12_340);
        assert_eq!(l.lines[0].text, "first placeholder line");
    }

    #[test]
    fn parses_millisecond_timestamps() {
        let l = Lyrics::parse("[01:02.345]second placeholder line");
        assert_eq!(l.lines[0].time_ms, 62_345);
    }

    #[test]
    fn expands_multiple_timestamps_on_one_line() {
        let l = Lyrics::parse("[00:10.00][00:50.00]repeated placeholder");
        assert_eq!(l.lines.len(), 2);
        assert_eq!(l.lines[0].time_ms, 10_000);
        assert_eq!(l.lines[1].time_ms, 50_000);
        assert_eq!(l.lines[1].text, "repeated placeholder");
    }

    #[test]
    fn skips_metadata_tags() {
        let l =
            Lyrics::parse("[ar:Placeholder Artist]\n[ti:Placeholder Title]\n[00:01.00]only line");
        assert_eq!(l.lines.len(), 1);
        assert_eq!(l.lines[0].text, "only line");
    }

    #[test]
    fn reads_offset_tag() {
        let l = Lyrics::parse("[offset:-500]\n[00:10.00]placeholder");
        assert_eq!(l.offset_ms, -500);
        let p = Lyrics::parse("[offset:+250]\n[00:10.00]placeholder");
        assert_eq!(p.offset_ms, 250);
    }

    #[test]
    fn sorts_out_of_order_timestamps() {
        let l = Lyrics::parse("[00:30.00]later\n[00:05.00]earlier");
        assert_eq!(l.lines[0].text, "earlier");
        assert_eq!(l.lines[1].text, "later");
    }

    #[test]
    fn keeps_blank_instrumental_entries() {
        let l = Lyrics::parse("[00:01.00]placeholder\n[00:20.00]");
        assert_eq!(l.lines.len(), 2);
        assert_eq!(l.lines[1].text, "");
    }

    #[test]
    fn skips_malformed_lines_but_keeps_valid_neighbours() {
        let l =
            Lyrics::parse("[00:01.00]good one\nnot a lyric line\n[garbage]\n[00:02.00]good two");
        assert_eq!(l.lines.len(), 2);
        assert_eq!(l.lines[0].text, "good one");
        assert_eq!(l.lines[1].text, "good two");
    }

    #[test]
    fn strips_enhanced_word_tags() {
        let l = Lyrics::parse("[00:01.00]<00:01.00>alpha <00:01.50>beta");
        assert_eq!(l.lines[0].text, "alpha beta");
    }

    #[test]
    fn handles_bom_and_crlf() {
        let l = Lyrics::parse("\u{feff}[00:01.00]placeholder one\r\n[00:02.00]placeholder two\r\n");
        assert_eq!(l.lines.len(), 2);
        assert_eq!(l.lines[0].text, "placeholder one");
        assert_eq!(l.lines[1].text, "placeholder two");
    }

    #[test]
    fn empty_and_whitespace_inputs_produce_no_lines() {
        assert!(Lyrics::parse("").lines.is_empty());
        assert!(Lyrics::parse("   \n\n  ").lines.is_empty());
        assert!(Lyrics::parse("").is_empty());
    }

    #[test]
    fn is_empty_when_every_line_is_blank() {
        assert!(Lyrics::parse("[00:01.00]\n[00:02.00]").is_empty());
        assert!(!Lyrics::parse("[00:01.00]placeholder").is_empty());
    }

    #[test]
    fn active_line_before_first_timestamp_is_none() {
        let l = Lyrics::parse("[00:10.00]placeholder");
        assert_eq!(l.active_line_at(0), None);
        assert_eq!(l.active_line_at(9_999), None);
    }

    #[test]
    fn active_line_at_boundaries() {
        let l = Lyrics::parse("[00:10.00]a\n[00:20.00]b\n[00:30.00]c");
        assert_eq!(l.active_line_at(10_000), Some(0));
        assert_eq!(l.active_line_at(15_000), Some(0));
        assert_eq!(l.active_line_at(20_000), Some(1));
        assert_eq!(l.active_line_at(999_000), Some(2));
    }

    #[test]
    fn active_line_applies_offset() {
        let l = Lyrics::parse("[offset:1000]\n[00:10.00]placeholder");
        assert_eq!(l.active_line_at(9_000), Some(0));
        assert_eq!(l.active_line_at(8_999), None);
    }

    #[test]
    fn active_line_on_empty_lyrics_is_none() {
        assert_eq!(Lyrics::parse("").active_line_at(1_000), None);
    }
}

#[cfg(test)]
mod unsynced_tests {
    use super::*;

    #[test]
    fn synced_lyrics_are_marked_synced() {
        let l = Lyrics::parse("[00:01.00]placeholder line");
        assert!(l.synced);
    }

    #[test]
    fn unsynced_parse_keeps_every_text_line() {
        let l = Lyrics::parse_unsynced("first line\nsecond line\nthird line");
        assert_eq!(l.lines.len(), 3);
        assert_eq!(l.lines[0].text, "first line");
        assert_eq!(l.lines[2].text, "third line");
        assert!(!l.synced);
    }

    #[test]
    fn unsynced_parse_skips_metadata_and_blank_lines() {
        let l = Lyrics::parse_unsynced("[ar:Placeholder]\n\nfirst line\n   \nsecond line");
        assert_eq!(l.lines.len(), 2);
        assert_eq!(l.lines[0].text, "first line");
    }

    #[test]
    fn unsynced_parse_of_blank_input_is_empty() {
        assert!(Lyrics::parse_unsynced("").is_empty());
        assert!(Lyrics::parse_unsynced("[ar:Only Metadata]").is_empty());
    }

    #[test]
    fn unsynced_lyrics_have_no_active_line() {
        // Without timestamps there is nothing to follow, so the view must not
        // highlight or scroll.
        let l = Lyrics::parse_unsynced("first line\nsecond line");
        assert_eq!(l.active_line_at(0), None);
        assert_eq!(l.active_line_at(999_000), None);
    }
}
