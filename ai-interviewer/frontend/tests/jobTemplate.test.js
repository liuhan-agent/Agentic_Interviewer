const assert = require("node:assert/strict");
const test = require("node:test");

const {
  jobTemplateAutofillValue,
  jobTemplateRequestPath,
} = require("../src/lib/job-template.ts");

test("autofills the default JD template before the user edits it", () => {
  assert.equal(
    jobTemplateAutofillValue({
      template: "岗位职责：\n- 负责 Java 后端开发",
      userEdited: false,
    }),
    "岗位职责：\n- 负责 Java 后端开发",
  );
});

test("does not overwrite a user-edited JD", () => {
  assert.equal(
    jobTemplateAutofillValue({
      template: "岗位职责：\n- 通用模板",
      userEdited: true,
    }),
    null,
  );
});

test("ignores blank JD templates", () => {
  assert.equal(
    jobTemplateAutofillValue({
      template: "   ",
      userEdited: false,
    }),
    null,
  );
});

test("builds the job template request path with direction and level", () => {
  assert.equal(
    jobTemplateRequestPath({
      direction: "java_backend",
      level: "junior",
    }),
    "/api/v1/interview/job-template?direction=java_backend&level=junior",
  );
});
