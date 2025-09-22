const API_BASE_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "";

type RequestOptions = RequestInit & { params?: Record<string, string | number | boolean | undefined> };

const buildUrl = (path: string, params?: RequestOptions["params"]): string => {
  const url = new URL(path, API_BASE_URL || "http://localhost:8000");

  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value === undefined) return;
      url.searchParams.set(key, String(value));
    });
  }

  return url.toString();
};

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { params, headers, ...rest } = options;
  const url = buildUrl(path, params);

  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...headers,
    },
    ...rest,
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`API request failed: ${response.status} ${body}`);
  }

  return response.json() as Promise<T>;
}

export const API = {
  fetch: apiFetch,
};

export type { RequestOptions };
