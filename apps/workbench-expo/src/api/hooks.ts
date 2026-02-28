import { useMemo } from "react";

import { ApiClient } from "@/api/client";
import { useSettingsContext } from "@/state/settings-context";

export function useApiClient(): ApiClient {
  const { settings } = useSettingsContext();
  return useMemo(
    () =>
      new ApiClient({
        baseUrl: settings.backendBaseUrl,
        mobileApiKey: settings.mobileApiKey,
      }),
    [settings.backendBaseUrl, settings.mobileApiKey],
  );
}
