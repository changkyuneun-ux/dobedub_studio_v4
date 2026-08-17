import { useEffect, useRef, useState } from "react";

export function useProtectedAssetUrl(rawUrl: string): string {
  // Login creates a HttpOnly cookie scoped to /api/files. Native image/video
  // requests then retain browser caching and video byte-range streaming
  // without loading each source file into a JavaScript Blob first.
  return rawUrl;
}

export function ProtectedImage({ src, alt }: { src: string; alt: string }) {
  const mediaUrl = useProtectedAssetUrl(src);
  return mediaUrl ? <img src={mediaUrl} alt={alt} decoding="async" loading="lazy" /> : null;
}

// 2026-08-12: "미리보기" 열 썸네일에 이미지만 있고 영상은 텍스트 배지("MP4" 등)만
// 보였던 문제 - 대부분의 출력이 영상이라 실질적으로 목록 전체가 텍스트뿐이었다.
// 별도 썸네일 생성 파이프라인(백엔드)이 없으므로, <video>에 controls 없이
// preload="metadata"만 줘서 브라우저가 로드하는 첫 프레임을 정지 이미지처럼
// 보여주는 방식으로 대체한다(자동재생 없음, 클릭 시엔 부모가 별도로 확대
// 모달을 연다 - 이 컴포넌트 자체는 클릭 핸들러를 갖지 않는다).
export function ProtectedVideoThumb({ src, alt }: { src: string; alt: string }) {
  const mediaUrl = useProtectedAssetUrl(src);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [isNearViewport, setIsNearViewport] = useState(false);

  useEffect(() => {
    const element = videoRef.current;
    if (!element || !mediaUrl) {
      return undefined;
    }
    if (typeof IntersectionObserver === "undefined") {
      setIsNearViewport(true);
      return undefined;
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) {
          setIsNearViewport(true);
          observer.disconnect();
        }
      },
      { rootMargin: "240px 0px" },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [mediaUrl]);

  return mediaUrl ? <video ref={videoRef} src={isNearViewport ? mediaUrl : undefined} muted playsInline preload="metadata" aria-label={alt} /> : null;
}

export function ProtectedAssetPreview({ src, isVideo, alt }: { src: string; isVideo?: boolean; alt: string }) {
  const mediaUrl = useProtectedAssetUrl(src);
  if (!mediaUrl) {
    return null;
  }
  return isVideo
    ? <video src={mediaUrl} controls playsInline preload="metadata" />
    : <img src={mediaUrl} alt={alt} decoding="async" />;
}
