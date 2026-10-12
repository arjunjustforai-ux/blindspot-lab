import { describe, expect, it } from "vitest";
import { difficultyLabel, fmtBytes, fmtTs, masteryColor, pct } from "./utils";

describe("formatting helpers", () => {
  it("formats percentages and missing values", () => {
    expect(pct(0.256)).toBe("26%");
    expect(pct(0.256, 1)).toBe("25.6%");
    expect(pct(null)).toBe("—");
    expect(pct(Number.NaN)).toBe("—");
  });

  it("formats timestamps like the citation labels", () => {
    expect(fmtTs(41.9)).toBe("00:41");
    expect(fmtTs(3725)).toBe("1:02:05");
    expect(fmtTs(null)).toBe("—");
  });

  it("formats byte sizes", () => {
    expect(fmtBytes(512)).toBe("512 B");
    expect(fmtBytes(270 * 1024)).toBe("270 KB");
    expect(fmtBytes(2.5 * 1024 * 1024)).toBe("2.5 MB");
  });

  it("maps mastery labels and difficulty", () => {
    expect(masteryColor("mastered")).toBe("#34d399");
    expect(masteryColor(undefined)).toBe(masteryColor("unassessed"));
    expect(difficultyLabel(2)).toBe("Medium");
    expect(difficultyLabel(9)).toBe("Level 9");
  });
});
