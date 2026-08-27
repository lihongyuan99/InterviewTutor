import type { Resume } from "../../lib/api";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-900">
      <h3 className="mb-3 text-sm font-semibold text-gray-800 dark:text-gray-200">{title}</h3>
      {children}
    </section>
  );
}

function Chip({ text }: { text: string }) {
  if (!text) return null;
  return (
    <span className="inline-flex items-center rounded-full bg-indigo-50 px-2.5 py-0.5 text-xs text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300">
      {text}
    </span>
  );
}

function Empty({ text }: { text: string }) {
  return <p className="text-sm text-gray-400">{text}</p>;
}

export function ResumePreview({ resume }: { resume: Resume }) {
  const hasProjects = resume.projects.length > 0;
  const hasSkills = resume.skills.length > 0;

  return (
    <div className="space-y-4">
      {/* 基本信息 */}
      <Section title="基本信息">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
          <span className="font-medium text-gray-900 dark:text-white">
            {resume.name || "（未识别姓名）"}
          </span>
          {resume.target_role && (
            <span className="text-gray-500">目标岗位：{resume.target_role}</span>
          )}
          {resume.target_companies.length > 0 && (
            <span className="text-gray-500">
              目标公司：{resume.target_companies.join(" / ")}
            </span>
          )}
        </div>
        {resume.summary && (
          <p className="mt-2 text-sm leading-6 text-gray-600 dark:text-gray-300">{resume.summary}</p>
        )}
      </Section>

      {/* 项目经历（深挖核心） */}
      <Section title={`项目经历（${resume.projects.length}）`}>
        {hasProjects ? (
          <div className="space-y-4">
            {resume.projects.map((project, index) => (
              <div key={index} className="border-l-2 border-indigo-200 pl-3 dark:border-indigo-800">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-gray-800 dark:text-gray-200">{project.name}</span>
                  {project.period && <span className="text-xs text-gray-400">{project.period}</span>}
                </div>
                {project.description && (
                  <p className="mt-1 text-sm leading-6 text-gray-600 dark:text-gray-300">
                    {project.description}
                  </p>
                )}
                {project.tech_stack.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {project.tech_stack.map((tech) => (
                      <Chip key={tech} text={tech} />
                    ))}
                  </div>
                )}
                {project.metrics.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {project.metrics.map((metric) => (
                      <Chip key={metric} text={metric} />
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <Empty text="未识别到项目经历" />
        )}
      </Section>

      {/* 技能 */}
      <Section title={`技能（${resume.skills.length}）`}>
        {hasSkills ? (
          <div className="flex flex-wrap gap-2">
            {resume.skills.map((skill, index) => (
              <span
                key={index}
                className="inline-flex items-center gap-1 rounded-lg border border-gray-200 px-2.5 py-1 text-xs text-gray-700 dark:border-gray-700 dark:text-gray-300"
              >
                {skill.name}
                {skill.level && (
                  <span className="text-gray-400">· {skill.level}</span>
                )}
              </span>
            ))}
          </div>
        ) : (
          <Empty text="未识别到技能" />
        )}
      </Section>

      {/* 教育 */}
      {resume.educations.length > 0 && (
        <Section title="教育经历">
          <div className="space-y-2">
            {resume.educations.map((edu, index) => (
              <div key={index} className="text-sm text-gray-700 dark:text-gray-300">
                <span className="font-medium">{edu.school}</span>
                {edu.degree && <span className="ml-2 text-gray-500">{edu.degree}</span>}
                {edu.major && <span className="ml-2 text-gray-500">{edu.major}</span>}
                {(edu.start || edu.end) && (
                  <span className="ml-2 text-gray-400">
                    {edu.start} - {edu.end}
                  </span>
                )}
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* 工作经历 */}
      {resume.works.length > 0 && (
        <Section title="工作经历">
          <div className="space-y-3">
            {resume.works.map((work, index) => (
              <div key={index} className="text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-gray-800 dark:text-gray-200">{work.company}</span>
                  {work.role && <span className="text-gray-500">{work.role}</span>}
                  {(work.start || work.end) && (
                    <span className="text-gray-400">
                      {work.start} - {work.end}
                    </span>
                  )}
                </div>
                {work.description && (
                  <p className="mt-1 text-gray-600 dark:text-gray-300">{work.description}</p>
                )}
                {work.tech_stack.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {work.tech_stack.map((tech) => (
                      <Chip key={tech} text={tech} />
                    ))}
                  </div>
                )}
                {work.metrics.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {work.metrics.map((metric) => (
                      <Chip key={metric} text={metric} />
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* 荣誉 */}
      {resume.honors.length > 0 && (
        <Section title="荣誉奖项">
          <ul className="list-inside list-disc space-y-1 text-sm text-gray-600 dark:text-gray-300">
            {resume.honors.map((honor, index) => (
              <li key={index}>{honor}</li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}
