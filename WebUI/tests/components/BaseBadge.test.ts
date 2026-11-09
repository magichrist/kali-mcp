import { describe, it, expect } from "vitest";
import { mount } from "@vue/test-utils";
import BaseBadge from "@/components/common/BaseBadge.vue";

describe("BaseBadge", () => {
  it("renders slot content", () => {
    const wrapper = mount(BaseBadge, { slots: { default: "ok" } });
    expect(wrapper.find(".run-state").text()).toBe("ok");
  });

  it("applies ok variant class", () => {
    const wrapper = mount(BaseBadge, { props: { variant: "ok" }, slots: { default: "ok" } });
    expect(wrapper.classes()).toContain("ok");
    expect(wrapper.classes()).toContain("run-run");
  });

  it("applies failed variant class", () => {
    const wrapper = mount(BaseBadge, { props: { variant: "failed" }, slots: { default: "failed" } });
    expect(wrapper.classes()).toContain("failed");
  });

  it("applies warn variant class", () => {
    const wrapper = mount(BaseBadge, { props: { variant: "warn" }, slots: { default: "warn" } });
    expect(wrapper.classes()).toContain("warn");
  });

  it("applies default variant with no extra state class", () => {
    const wrapper = mount(BaseBadge, { props: { variant: "default" }, slots: { default: "d" } });
    expect(wrapper.classes()).toContain("run-state");
    expect(wrapper.classes()).not.toContain("ok");
    expect(wrapper.classes()).not.toContain("failed");
    expect(wrapper.classes()).not.toContain("warn");
  });

  it("applies accent variant", () => {
    const wrapper = mount(BaseBadge, { props: { variant: "accent" }, slots: { default: "a" } });
    expect(wrapper.classes()).toContain("run-state");
  });
});
