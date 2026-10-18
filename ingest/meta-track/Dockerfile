FROM node:22-alpine@sha256:37a91f2ffc7ef9ef27e1db56e2d4fbc8a7f02e999a8b02bbd8e7c92bb7c7afc7

WORKDIR /app

# Copy package files
COPY package.json package-lock.json ./

# Install production dependencies only
RUN npm ci --omit=dev && npm cache clean --force

# Copy source code
COPY src ./src

# Create non-root user
RUN addgroup -g 1001 -S nodejs && adduser -S nodejs -u 1001

# Switch to non-root user
USER nodejs

# Health check script
HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=1 \
  CMD [ -f /tmp/meta-publisher-health ] && \
      [ $(( $(date +%s000) - $(cat /tmp/meta-publisher-health) )) -lt 5000 ] && \
      echo "OK" || exit 1

# Entry point
ENTRYPOINT ["node", "src/index.mjs"]
CMD ["publish"]
