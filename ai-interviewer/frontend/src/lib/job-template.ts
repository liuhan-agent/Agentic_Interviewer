export function jobTemplateAutofillValue(args: {
  template?: string | null;
  userEdited: boolean;
}): string | null {
  const template = args.template?.trim();
  if (!template || args.userEdited) {
    return null;
  }
  return template;
}

export function jobTemplateRequestPath(args: {
  direction: string;
  level?: string;
}): string {
  const params = new URLSearchParams({ direction: args.direction });
  if (args.level) {
    params.set("level", args.level);
  }
  return `/api/v1/interview/job-template?${params.toString()}`;
}
