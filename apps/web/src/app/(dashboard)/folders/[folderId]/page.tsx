import { Suspense } from "react";

import { FolderWorkspace, FolderWorkspaceSkeleton } from "@/components/records/folder-workspace";

// folderId is only known at request time, so reading it must sit inside Suspense (Cache Components).
export default function FolderPage({ params }: PageProps<"/folders/[folderId]">) {
  return (
    <Suspense fallback={<FolderWorkspaceSkeleton />}>
      {params.then(({ folderId }) => (
        <FolderWorkspace folderId={folderId} />
      ))}
    </Suspense>
  );
}
