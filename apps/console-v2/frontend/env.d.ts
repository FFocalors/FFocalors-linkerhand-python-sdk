/// <reference types="vite/client" />

declare module '*?worker&classic' {
  const WorkerConstructor: { new (options?: WorkerOptions): Worker };
  export default WorkerConstructor;
}

declare function importScripts(...urls: string[]): void;
