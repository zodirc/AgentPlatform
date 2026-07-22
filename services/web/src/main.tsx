import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import { EndUserAuthProvider } from "./shared/auth/EndUserAuth";
import { ThemeProvider } from "./shared/theme/ThemeProvider";
import { applyTheme, readStoredTheme } from "./shared/theme/theme";
import "./index.css";

applyTheme(readStoredTheme());

const queryClient = new QueryClient();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <EndUserAuthProvider>
        <ThemeProvider>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </ThemeProvider>
      </EndUserAuthProvider>
    </QueryClientProvider>
  </StrictMode>,
);
