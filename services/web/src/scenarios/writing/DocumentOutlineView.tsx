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
  // Title lives on the parent Card ("文档大纲"); avoid a second label.
  return <SectionEditor value={String(artifact.content)} />;
}
