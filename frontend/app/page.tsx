/** Root route redirects to the underwriting pipeline (specs/13 §1).
 * (The scaffold's todo demo previously lived here — removed in P6.) */
import { redirect } from "next/navigation";

export default function Home() {
  redirect("/pipeline");
}
