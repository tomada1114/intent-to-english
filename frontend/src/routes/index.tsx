import { createFileRoute } from "@tanstack/react-router";
import { HomeScreen } from "../features/sessions";

export const Route = createFileRoute("/")({
  component: HomeScreen,
});
