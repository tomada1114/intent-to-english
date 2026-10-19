import { Link } from "@tanstack/react-router";
import { PRIMARY_BUTTON } from "../lib/ui";

/** S4: an unknown session or an unmatched path, with the way back home. */
export function NotFound() {
  return (
    <div className="mx-auto w-full max-w-[880px] space-y-6 px-4 py-12">
      <h1 className="text-xl font-bold">この会話は見つかりませんでした。</h1>
      <Link to="/" className={PRIMARY_BUTTON}>
        会話一覧へ
      </Link>
    </div>
  );
}
