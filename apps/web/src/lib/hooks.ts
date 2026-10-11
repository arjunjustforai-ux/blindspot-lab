"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { api } from "./api";
import type { Course } from "./types";

export function useCourses(enabled = true) {
  return useQuery({ queryKey: ["courses"], queryFn: () => api<Course[]>("/api/courses"), enabled });
}

export function useCourseId(): string | undefined {
  const p = useParams<{ courseId?: string }>();
  return p?.courseId;
}

export function useCourse(courseId: string | undefined) {
  return useQuery({
    queryKey: ["course", courseId],
    queryFn: () => api<Course>(`/api/courses/${courseId}`),
    enabled: !!courseId,
  });
}

const LAST = "blindspot.lastCourse";
export function rememberCourse(id: string) {
  if (typeof window !== "undefined") window.localStorage.setItem(LAST, id);
}
export function lastCourse(): string | null {
  return typeof window === "undefined" ? null : window.localStorage.getItem(LAST);
}
