import { useEffect, useState } from "react";
import { apiClient } from "../api/client";

export function useProtectedAssetUrl(rawUrl: string): string {
  const [mediaUrl, setMediaUrl] = useState("");

  useEffect(() => {
    let active = true;
    let objectUrl = "";
    if (!rawUrl) {
      setMediaUrl("");
      return undefined;
    }
    if (!rawUrl.startsWith("/api/files/")) {
      setMediaUrl(rawUrl);
      return undefined;
    }
    apiClient.assetBlob(rawUrl)
      .then((blob) => {
        if (!active) {
          return;
        }
        objectUrl = URL.createObjectURL(blob);
        setMediaUrl(objectUrl);
      })
      .catch(() => {
        if (active) {
          setMediaUrl("");
        }
      });
    return () => {
      active = false;
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [rawUrl]);

  return mediaUrl;
}

export function ProtectedImage({ src, alt }: { src: string; alt: string }) {
  const mediaUrl = useProtectedAssetUrl(src);
  return mediaUrl ? <img src={mediaUrl} alt={alt} /> : null;
}

// 2026-08-12: "미리보기" 열 썸네일에 이미지만 있고 영상은 텍스트 배지("MP4" 등)만
// 보였던 문제 - 대부분의 출력이 영상이라 실질적으로 목록 전체가 텍스트뿐이었다.
// 별도 썸네일 생성 파이프라인(백엔드)이 없으므로, <video>에 controls 없이
// preload="metadata"만 줘서 브라우저가 로드하는 첫 프레임을 정지 이미지처럼
// 보여주는 방식으로 대체한다(자동재생 없음, 클릭 시엔 부모가 별도로 확대
// 모달을 연다 - 이 컴포넌트 자체는 클릭 핸들러를 갖지 않는다).
export function ProtectedVideoThumb({ src, alt }: { src: string; alt: string }) {
  const mediaUrl = useProtectedAssetUrl(src);
  return mediaUrl ? <video src={mediaUrl} muted playsInline preload="metadata" aria-label={alt} /> : null;
}

export function ProtectedAssetPreview({ src, isVideo, alt }: { src: string; isVideo?: boolean; alt: string }) {
  const mediaUrl = useProtectedAssetUrl(src);
  if (!mediaUrl) {
    return null;
  }
  return isVideo
    ? <video src={mediaUrl} controls playsInline preload="metadata" />
    : <img src={mediaUrl} alt={alt} />;
}
