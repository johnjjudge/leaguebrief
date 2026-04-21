type AppConfig = {
  apiBaseUrl: string;
};

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim() || "/api";

export const appConfig: AppConfig = {
  apiBaseUrl: apiBaseUrl.replace(/\/$/, ""),
};
