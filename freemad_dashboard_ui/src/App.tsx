import React from "react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Toaster } from "@/components/ui/toaster";
import { Assembly } from "@/pages/Assembly";

const App: React.FC = () => {
  return (
    <TooltipProvider>
      <Toaster />
      <Assembly />
    </TooltipProvider>
  );
};

export default App;

