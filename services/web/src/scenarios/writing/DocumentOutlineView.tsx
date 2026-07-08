import { SectionEditor } from "../../components/SectionEditor";

type OutlineArtifact = {
  type?: string;
  content?: string;
};

type Props = {
  artifact: OutlineArtifact | undefined;
};

export function DocumentOutlineView({ artifact }: Props) {
  if (!artifact?.content) return null;
  return (
    <SectionEditor title="outline" value={String(artifact.content)} />
  );
}
