import { describe, expect, it } from "vitest";
import { blankImage } from "./__fixtures__/synthetic";
import { encodeCut, serializeSummary, verifyPngOutput } from "./artifacts";

describe("webtoon cut artifacts", () => {
  it("writes UTF-8 BOM and exact summary columns", () => {
    const bytes = serializeSummary([summaryRow()]);
    const csv = new TextDecoder("utf-8", { ignoreBOM: true }).decode(bytes);

    expect([...bytes.slice(0, 3)]).toEqual([0xef, 0xbb, 0xbf]);
    expect(csv.startsWith("\uFEFFunit_id,source_path,page,cut,filename,mode,x0,y0,x1,y1,width,height,confidence,flag,elapsed_ms,status,error\r\n")).toBe(true);
  });

  it("encodes every generated image as PNG without changing crop dimensions", async () => {
    const blob = await encodeCut(blankImage(640, 480), { x0: 10, y0: 20, x1: 610, y1: 420 });

    expect(blob.type).toBe("image/png");
    await expect(verifyPngOutput(new File([blob], "cut.png"), { width: 600, height: 400 })).resolves.toBe(true);
  });
});

function summaryRow() {
  return {
    unit_id: "image:page.jpg",
    source_path: "page.jpg",
    page: "",
    cut: 1,
    filename: "page-01.png",
    mode: "fullpage",
    x0: 0,
    y0: 0,
    x1: 100,
    y1: 100,
    width: 100,
    height: 100,
    confidence: 0.1,
    flag: "fullpage",
    elapsed_ms: 1,
    status: "completed",
    error: ""
  };
}
