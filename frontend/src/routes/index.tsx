import { createFileRoute } from "@tanstack/react-router";
import { TodosScreen } from "../features/todos";

const APP_NAME = "Intent to English";

export const Route = createFileRoute("/")({
  component: Index,
});

function Index() {
  return (
    <div className="space-y-6 p-4">
      <h1 className="text-2xl font-semibold">{APP_NAME}</h1>
      <TodosScreen />
    </div>
  );
}
