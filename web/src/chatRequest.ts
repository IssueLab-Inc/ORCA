/** One client turn owns both its stream and page events. Invalidating never edits completed chat history. */
export interface ChatRequest {
  signal: AbortSignal;
  isCurrent: () => boolean;
  cancel: () => void;
  finish: () => void;
}

export class ChatRequestOwner {
  private generation = 0;
  private request: AbortController | null = null;

  invalidate() {
    ++this.generation; // Close the event boundary before abort listeners or late callbacks can run.
    const request = this.request;
    this.request = null;
    request?.abort();
  }

  capture() {
    const generation = this.generation;
    return () => this.generation === generation;
  }

  begin(): ChatRequest {
    this.invalidate();
    const generation = this.generation, controller = new AbortController();
    this.request = controller;
    let finished = false;
    return {
      signal: controller.signal,
      isCurrent: () => !finished && !controller.signal.aborted && this.generation === generation,
      cancel: () => {
        if (this.generation === generation) this.invalidate();
        else controller.abort();
      },
      finish: () => {
        finished = true;
        if (this.request === controller) this.request = null;
      },
    };
  }
}
