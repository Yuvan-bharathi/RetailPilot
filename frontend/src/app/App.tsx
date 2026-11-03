import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, RouterProvider } from "react-router";

import { HomePage } from "../pages/HomePage.tsx";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 300_000, retry: 1 },
  },
});

const router = createBrowserRouter([{ path: "/", element: <HomePage /> }]);

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
