"use client";
import { useEffect } from "react";
import { getToken } from "@/lib/api";

export default function Home() {
  useEffect(() => {
    window.location.replace(getToken() ? "/projects" : "/login");
  }, []);
  return null;
}
