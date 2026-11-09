import { describe, it, expect } from "vitest";
import { mount } from "@vue/test-utils";
import BaseButton from "@/components/common/BaseButton.vue";

describe("BaseButton", () => {
  it("renders label via default slot", () => {
    const wrapper = mount(BaseButton, {
      props: { variant: "primary" },
      slots: { default: "Save" },
    });
    expect(wrapper.find("button").text()).toBe("Save");
  });

  it("applies variant class", () => {
    const wrapper = mount(BaseButton, {
      props: { variant: "danger" },
      slots: { default: "Delete" },
    });
    expect(wrapper.classes()).toContain("btn");
    expect(wrapper.classes()).toContain("danger");
  });

  it("defaults to no variant class", () => {
    const wrapper = mount(BaseButton, {
      slots: { default: "OK" },
    });
    expect(wrapper.classes()).toContain("btn");
    expect(wrapper.classes()).not.toContain("primary");
    expect(wrapper.classes()).not.toContain("danger");
  });

  it("emits click when the button is clicked", async () => {
    const wrapper = mount(BaseButton, {
      props: { variant: "ghost" },
      slots: { default: "Run" },
    });
    await wrapper.find("button").trigger("click");
    expect(wrapper.emitted("click")).toBeTruthy();
    expect(wrapper.emitted("click")!.length).toBeGreaterThanOrEqual(1);
  });

  it("sets disabled attribute when disabled", () => {
    const wrapper = mount(BaseButton, {
      props: { disabled: true },
      slots: { default: "X" },
    });
    expect(wrapper.find("button").attributes("disabled")).toBeDefined();
  });

  it("does not set disabled attribute by default", () => {
    const wrapper = mount(BaseButton, {
      slots: { default: "X" },
    });
    expect(wrapper.find("button").attributes("disabled")).toBeUndefined();
  });
});
