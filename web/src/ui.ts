// The class strings the v1 Chats and Search components still share, on shadcn's tokens until tickets 04 and 05
// replace those components with the real shadcn primitives.
export const inputClass =
  "rounded-md border border-input bg-background px-3 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/50 focus:outline-none";
export const buttonClass =
  "rounded-md bg-primary px-3.5 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-45";
export const outlineButtonClass =
  "rounded-md border border-input px-3 py-1 text-sm font-medium hover:bg-accent hover:text-accent-foreground disabled:opacity-45";
export const quietButtonClass =
  "rounded-md px-2 py-1 text-sm text-muted-foreground hover:bg-accent hover:text-accent-foreground disabled:opacity-45";
export const dangerButtonClass =
  "rounded-md px-2 py-1 text-sm text-destructive hover:bg-destructive/10 disabled:opacity-45";
// A label wrapping a checkbox, drawn as a pill that fills when ticked.
export const chipClass =
  "flex cursor-pointer items-center gap-2 rounded-full border border-input bg-background px-3 py-1 text-sm text-muted-foreground hover:border-ring has-checked:border-primary has-checked:bg-muted has-checked:text-foreground";
export const sectionHeadingClass = "text-lg font-semibold tracking-tight";
export const alertClass = "mt-3 rounded-md border-l-4 border-destructive bg-destructive/10 px-3 py-2 text-sm text-destructive";
export const hintClass = "text-sm text-muted-foreground";

