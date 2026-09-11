import { Composition } from 'remotion'
import { HakusFirstRun, type FirstRunProps } from './compositions/HakusFirstRun'
import { HakusLongRunning, type LongRunningProps } from './compositions/HakusLongRunning'
import { HakusStartup } from './compositions/HakusStartup'

const FirstRunComposition = (props: Record<string, unknown>) => (
  <HakusFirstRun {...(props as unknown as FirstRunProps)} />
)

const LongRunningComposition = (props: Record<string, unknown>) => (
  <HakusLongRunning {...(props as unknown as LongRunningProps)} />
)

export const Root = () => (
  <>
    <Composition
      id="HakusStartup"
      component={HakusStartup}
      durationInFrames={90}
      fps={30}
      width={800}
      height={480}
      defaultProps={{}}
    />
    <Composition
      id="HakusFirstRun"
      component={FirstRunComposition}
      durationInFrames={180}
      fps={30}
      width={960}
      height={640}
      defaultProps={{ activeStep: 2 } satisfies FirstRunProps}
    />
    <Composition
      id="HakusLongRunning"
      component={LongRunningComposition}
      durationInFrames={180}
      fps={30}
      width={960}
      height={540}
      defaultProps={{
        title: 'Prepare workspace',
        phase: 'Planning',
        progress: 0.46,
        status: 'active',
      } satisfies LongRunningProps}
    />
  </>
)
