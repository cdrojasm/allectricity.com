// Entry of the public landing (landing.html), served by nginx on the root domain. The app is index.html.
import React from "react";
import { createRoot } from "react-dom/client";
import { LandingPage } from "./components/LandingPage.jsx";

createRoot(document.getElementById("root")).render(<LandingPage />);
