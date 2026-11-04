// vitest-axe 0.1 augments the legacy `Vi` namespace; register the matcher on Vitest's current Assertion type.
import "vitest";

declare module "vitest" {
  interface Assertion {
    toHaveNoViolations(): void;
  }
  interface AsymmetricMatchersContaining {
    toHaveNoViolations(): void;
  }
}
